# storage/user_db.py
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from threading import RLock
from typing import Iterable

from .models import CodeforcesBinding

"""
该模块主要实现数据的可持久化存储逻辑
通过异步 IO + 线程池，每次创建单独线程对数据库进行修改
引入写锁避免发生数据库写冲突，同时优先修改数据库、采用 WAL 预写日志，保证数据安全

模块注重线程安全和冲突避免，适合日常中小型并发场景，在高并发场景下可能会出现线程池枯竭、请求积压等情况，但在一般的 QQ 群内足够了
"""

class DataStorageHandler:
    """基于 SQLite 实现的 cf 信息绑定模块"""
    def __init__(
        self,
        db_path: str | Path,
        busy_timeout_ms: int = 5000,
    ) -> None:
        """初始化数据库连接、表结构和内存缓存。"""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # 可重入锁，使一个线程可以多次获取同一个锁，保证多线程环境下的数据一致性
        self._lock = RLock()

        # 内存索引映射，对群号、cf handle 与对应二元组分别构建映射，提升查询效率 
        self._bindings: dict[tuple[str, str], CodeforcesBinding] = {}
        self._group_index: dict[str, set[tuple[str, str]]] = {}
        self._handle_index: dict[str, set[tuple[str, str]]] = {}

        # 与数据库建立连接
        self._conn = sqlite3.connect(
            self.db_path,
            timeout=busy_timeout_ms / 1000,
            isolation_level="IMMEDIATE",
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row        # 行工厂以字典式访问

        self._configure_connection(busy_timeout_ms)
        self._init_schema()
        self.reload_cache()

    def _configure_connection(self, busy_timeout_ms: int) -> None:
        """连接参数配置：同步策略、日志策略、超时时长等"""
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            self._conn.execute("PRAGMA wal_autocheckpoint=1000")

    def _init_schema(self) -> None:
        """表创建逻辑"""
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cf_bindings (
                    user_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    cf_handle TEXT NOT NULL,
                    enable_broadcast INTEGER NOT NULL DEFAULT 1
                        CHECK (enable_broadcast IN (0, 1)),
                    last_ac_fingerprint TEXT DEFAULT NULL,
                    updated_at INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, group_id)
                );

                CREATE INDEX IF NOT EXISTS idx_bind_group
                ON cf_bindings(group_id);

                CREATE INDEX IF NOT EXISTS idx_bind_handle
                ON cf_bindings(cf_handle);
                """
            )

    def _run_write(self, sql: str, params: Iterable[object] = ()) -> sqlite3.Cursor:
        """写操作逻辑：线程先获取锁，然后通过事务提交修改或回滚修改"""
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(sql, tuple(params))
                return cursor

    @staticmethod
    def _normalize_id(value: str | int) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("user_id and group_id cannot be empty")
        return normalized

    @staticmethod
    def _normalize_handle(value: str) -> str:
        handle = value.strip()
        if not handle:
            raise ValueError("cf_handle cannot be empty")
        return handle

    @staticmethod
    def _row_to_binding(row: sqlite3.Row) -> CodeforcesBinding:
        """将返回行对象加工为规定的数据类"""
        return CodeforcesBinding(
            user_id=row["user_id"],
            group_id=row["group_id"],
            cf_handle=row["cf_handle"],
            enable_broadcast=bool(row["enable_broadcast"]),
            last_ac_fingerprint=row["last_ac_fingerprint"],
            updated_at=int(row["updated_at"]),
        )

    def _replace_cache(self, bindings: Iterable[CodeforcesBinding]) -> None:
        """内存更新逻辑"""
        # 清空内存中的所有映射数据
        self._bindings.clear()
        self._group_index.clear()
        self._handle_index.clear()
        for binding in bindings:
            self._cache_add(binding)

    def _cache_add(self, binding: CodeforcesBinding) -> None:
        """向内存索引添加单条记录，调用方需保证 key 不重复"""
        key = (binding.user_id, binding.group_id)
        self._bindings[key] = binding
        self._group_index.setdefault(binding.group_id, set()).add(key)
        self._handle_index.setdefault(binding.cf_handle.casefold(), set()).add(key)

    def _cache_put(self, binding: CodeforcesBinding) -> None:
        """向内存中添加 / 更新单条记录"""
        key = (binding.user_id, binding.group_id)
        # 存在相同 key 的记录，则将旧记录删除
        old_binding = self._bindings.get(key)
        if old_binding is not None:
            self._cache_remove(old_binding.user_id, old_binding.group_id)
        
        # 向内存添加对应数据，已经保证 binding 不存在于内存中
        self._cache_add(binding)

    def _cache_remove(self, user_id: str, group_id: str) -> CodeforcesBinding | None:
        """删除内存中指定的 key，并返回对应的 CodeforcesBinding 对象"""
        key = (user_id, group_id)
        binding = self._bindings.pop(key, None)
        if binding is None:
            return None

        group_keys = self._group_index.get(group_id)
        if group_keys is not None:
            group_keys.discard(key)
            if not group_keys:
                self._group_index.pop(group_id, None)

        handle_key = binding.cf_handle.casefold()
        handle_keys = self._handle_index.get(handle_key)
        if handle_keys is not None:
            handle_keys.discard(key)
            if not handle_keys:
                self._handle_index.pop(handle_key, None)

        return binding

    def reload_cache(self) -> None:
        """从数据库中加载所有数据至内存"""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT user_id, group_id, cf_handle, enable_broadcast,
                       last_ac_fingerprint, updated_at
                FROM cf_bindings
                """
            ).fetchall()
            self._replace_cache(self._row_to_binding(row) for row in rows)

    async def areload_cache(self) -> None:
        """线程方法：从数据库中加载所有数据至内存"""
        await asyncio.to_thread(self.reload_cache)

    def bind_user(
        self,
        user_id: str | int,
        group_id: str | int,
        cf_handle: str,
        enable_broadcast: bool | None = None,
    ) -> CodeforcesBinding:
        """线程方法：用户绑定逻辑"""
        # 规范化传入参数
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)
        cf_handle = self._normalize_handle(cf_handle)
        updated_at = int(time.time())

        with self._lock:
            # 通过键值对获取对应绑定信息
            current = self._bindings.get((user_id, group_id))
            # 若信息不为空，则记录指纹，否则置为空
            last_ac_fingerprint = current.last_ac_fingerprint if current else None
            """
            实际解析为
            broadcast_enabled = (
                current.enable_broadcast
                if enable_broadcast is None and current is not None
                else (
                    True
                    if enable_broadcast is None
                    else bool(enable_broadcast)
                )
            )
            即
            if enable_broadcast is None and current is not None:
                broadcast_enabled = current.enable_broadcast
            else:
                if enable_broadcast is None:
                    broadcast_enabled = True
                else:
                    broadcast_enabled = bool(enable_broadcast)
            原语句可读性较差，通过右结合规则解析如上，虽篇幅较长，但可读性较好
            """
            broadcast_enabled = (
                current.enable_broadcast
                if enable_broadcast is None and current is not None
                else (
                    True
                    if enable_broadcast is None
                    else bool(enable_broadcast)    
                )
            )
            # 调用写操作逻辑，更新持久化数据
            self._run_write(
                """
                INSERT INTO cf_bindings (
                    user_id, group_id, cf_handle, enable_broadcast,
                    last_ac_fingerprint, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, group_id) DO UPDATE SET
                    cf_handle = excluded.cf_handle,
                    enable_broadcast = excluded.enable_broadcast,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    group_id,
                    cf_handle,
                    int(broadcast_enabled),
                    last_ac_fingerprint,
                    updated_at,
                ),
            )
            # 构建 CodeForcesBinding 结构，用于更新内存数据
            binding = CodeforcesBinding(
                user_id=user_id,
                group_id=group_id,
                cf_handle=cf_handle,
                enable_broadcast=broadcast_enabled,
                last_ac_fingerprint=last_ac_fingerprint,
                updated_at=updated_at,
            )
            # 更新逻辑，向内存中添加这个 binding 条目
            self._cache_put(binding)
            return binding

    async def abind_user(
        self,
        user_id: str | int,
        group_id: str | int,
        cf_handle: str,
        enable_broadcast: bool | None = None,
    ) -> CodeforcesBinding:
        """异步 IO：创建单独线程执行用户绑定操作，保证数据一致性"""
        return await asyncio.to_thread(
            self.bind_user,
            user_id,
            group_id,
            cf_handle,
            enable_broadcast,
        )

    def unbind_user(self, user_id: str | int, group_id: str | int) -> bool:
        """线程方法：解绑用户逻辑，并返回布尔值，表示是否删除成功"""
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)

        with self._lock:
            # 调用写数据库逻辑
            cursor = self._run_write(
                "DELETE FROM cf_bindings WHERE user_id = ? AND group_id = ?",
                (user_id, group_id),
            )
            removed = cursor.rowcount > 0
            # 内存同步更新
            if removed:
                self._cache_remove(user_id, group_id)
            return removed

    async def aunbind_user(self, user_id: str | int, group_id: str | int) -> bool:
        """异步 IO：创建单独线程执行用户解绑操作"""
        return await asyncio.to_thread(self.unbind_user, user_id, group_id)

    def get_binding(self, user_id: str | int, group_id: str | int) -> CodeforcesBinding | None:
        """线程方法：通过指定键值对查询内存数据"""
        key = (self._normalize_id(user_id), self._normalize_id(group_id))
        with self._lock:
            return self._bindings.get(key)

    async def aget_binding(
        self,
        user_id: str | int,
        group_id: str | int,
    ) -> CodeforcesBinding | None:
        """异步 IO：创建单独线程执行查询操作"""
        return await asyncio.to_thread(self.get_binding, user_id, group_id)

    def list_group_bindings(
        self,
        group_id: str | int,
        only_broadcast_enabled: bool = False,
    ) -> list[CodeforcesBinding]:
        """线程方法：通过群号获取对应群内所有的绑定信息"""
        group_id = self._normalize_id(group_id)
        with self._lock:
            # 获取键值对列表
            keys = self._group_index.get(group_id, set()).copy()
            # 通过键值对获取 binding 列表
            bindings = [self._bindings[key] for key in keys if key in self._bindings]

        # 若参数指定，则仅获取允许播报过题的用户信息
        if only_broadcast_enabled:
            bindings = [binding for binding in bindings if binding.enable_broadcast]
        return sorted(bindings, key=lambda binding: (binding.cf_handle.casefold(), binding.user_id))

    async def alist_group_bindings(
        self,
        group_id: str | int,
        only_broadcast_enabled: bool = False,
    ) -> list[CodeforcesBinding]:
        """异步 IO：创建单独线程获取群绑定信息列表"""
        return await asyncio.to_thread(
            self.list_group_bindings,
            group_id,
            only_broadcast_enabled,
        )

    def find_by_handle(self, cf_handle: str) -> list[CodeforcesBinding]:
        """线程方法：通过 handle 获取绑定信息列表"""
        handle_key = self._normalize_handle(cf_handle).casefold()
        with self._lock:
            keys = self._handle_index.get(handle_key, set()).copy()
            bindings = [self._bindings[key] for key in keys if key in self._bindings]
        return sorted(bindings, key=lambda binding: (binding.group_id, binding.user_id))

    async def afind_by_handle(self, cf_handle: str) -> list[CodeforcesBinding]:
        """异步 IO：创建单独线程获取用户绑定信息列表"""
        return await asyncio.to_thread(self.find_by_handle, cf_handle)

    def set_broadcast_enabled(
        self,
        user_id: str | int,
        group_id: str | int,
        enabled: bool,
    ) -> CodeforcesBinding | None:
        """线程方法：修改用户 enable 字段"""
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)
        updated_at = int(time.time())

        with self._lock:
            # 从内存中获取对应键值对
            current = self._bindings.get((user_id, group_id))
            if current is None:
                return None
            
            # 调用数据库修改逻辑
            cursor = self._run_write(
                """
                UPDATE cf_bindings
                SET enable_broadcast = ?, updated_at = ?
                WHERE user_id = ? AND group_id = ?
                """,
                (int(enabled), updated_at, user_id, group_id),
            )
            # 删除内存用户数据
            if cursor.rowcount <= 0:
                self._cache_remove(user_id, group_id)
                return None

            # 创建新条目，并向内存添加新的用户数据
            binding = CodeforcesBinding(
                user_id=user_id,
                group_id=group_id,
                cf_handle=current.cf_handle,
                enable_broadcast=enabled,
                last_ac_fingerprint=current.last_ac_fingerprint,
                updated_at=updated_at,
            )
            self._cache_put(binding)
            return binding

    async def aset_broadcast_enabled(
        self,
        user_id: str | int,
        group_id: str | int,
        enabled: bool,
    ) -> CodeforcesBinding | None:
        """异步 IO：创建单独线程执行线程方法"""
        return await asyncio.to_thread(
            self.set_broadcast_enabled,
            user_id,
            group_id,
            enabled,
        )

    def update_last_ac_fingerprint(
        self,
        user_id: str | int,
        group_id: str | int,
        fingerprint: str | None,
    ) -> CodeforcesBinding | None:
        """线程方法：更新用户记录指纹"""
        user_id = self._normalize_id(user_id)
        group_id = self._normalize_id(group_id)
        updated_at = int(time.time())

        with self._lock:
            current = self._bindings.get((user_id, group_id))
            if current is None:
                return None

            cursor = self._run_write(
                """
                UPDATE cf_bindings
                SET last_ac_fingerprint = ?, updated_at = ?
                WHERE user_id = ? AND group_id = ?
                """,
                (fingerprint, updated_at, user_id, group_id),
            )
            if cursor.rowcount <= 0:
                self._cache_remove(user_id, group_id)
                return None

            binding = CodeforcesBinding(
                user_id=user_id,
                group_id=group_id,
                cf_handle=current.cf_handle,
                enable_broadcast=current.enable_broadcast,
                last_ac_fingerprint=fingerprint,
                updated_at=updated_at,
            )
            self._cache_put(binding)
            return binding

    async def aupdate_last_ac_fingerprint(
        self,
        user_id: str | int,
        group_id: str | int,
        fingerprint: str | None,
    ) -> CodeforcesBinding | None:
        """异步 IO：更新指定用户的记录指纹"""
        return await asyncio.to_thread(
            self.update_last_ac_fingerprint,
            user_id,
            group_id,
            fingerprint,
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    async def aclose(self) -> None:
        """关闭数据库连接"""
        await asyncio.to_thread(self.close)
