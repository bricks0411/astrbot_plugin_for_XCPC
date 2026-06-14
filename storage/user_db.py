# storage/user_db.py
"""
用户绑定数据存储模块。

本模块使用 SQLite 保存 QQ 用户、AstrBot 会话和 Codeforces handle 的绑定关系。
数据库负责持久化，内存索引负责快速查询；每次写入成功后都会同步更新缓存。

并发策略：
- SQLite 连接启用 WAL，降低读写互相阻塞的概率。
- 写操作统一经过 _run_write，并在 RLock 保护下执行。
- 异步方法通过 asyncio.to_thread 调用同步方法，避免阻塞 AstrBot 事件循环。

业务约束：
- 同一个用户在同一个会话只能绑定一个 handle。
- 同一个会话内同一个 handle 只能被一个用户绑定。
- last_ac_fingerprint 用于自动播报去重，切换 handle 时需要重置。

维护要点：
- 数据库是权威状态，缓存只是加速查询的镜像。
- 写入路径必须先成功提交 SQLite，再更新内存缓存。
- 如果数据库写入失败，缓存不能提前变化。
- _bindings 以 (user_id, group_id) 为主键，匹配数据库主键。
- _group_index 用于快速列出某个会话内的全部绑定。
- _handle_index 用于判断某个 handle 在哪些会话中出现。
- handle 索引用 casefold 键，避免大小写差异绕过唯一性检查。
- 展示时仍保留用户输入的原始 handle 大小写。
- get_group_binding_by_handle 需要同时检查 handle 和 group_id。
- list 类方法返回排序后的列表，保证命令输出稳定。
- async 方法只是同步方法的线程包装，不重复实现业务逻辑。
- RLock 保护 SQLite 连接和三份缓存索引的一致性。
- check_same_thread=False 允许连接跨线程使用，但必须配合锁。
- busy_timeout 用于等待 SQLite 锁，减少短暂写冲突导致的失败。
- WAL 文件由 SQLite 管理，不需要业务代码手动清理。
- enable_broadcast 是用户维度开关，不影响绑定是否存在。
- last_ac_fingerprint 为 None 表示还没有建立播报基线。
- baseline: 前缀由自动推送模块写入，用于区分非 AC 基线。
- update_last_ac_fingerprint 只改指纹，不改变播报开关。
- close 只关闭连接，调用方需要先停止可能访问数据库的后台任务。
- 新增字段时需要同步建表 SQL、_row_to_binding 和写入语句。
- 新增查询入口时优先利用现有缓存索引，避免不必要的 SQL 查询。
- 这里的注释主要说明一致性和唯一性边界。
- reload_cache 会完全重建缓存，适合启动或手动修复后同步状态。
- _cache_put 会先删除旧索引再添加新索引，避免 handle 更新留下旧索引。
- 删除绑定时需要同时删除主缓存、群索引和 handle 索引。
- 数据库主键只约束用户在单个会话中的绑定。
- 额外唯一索引用于约束同一会话内 handle 不能被多人占用。
- set_broadcast_enabled 不改变 cf_handle，避免开关命令意外覆盖绑定。
- bind_user 切换 handle 时重置指纹，防止新账号继承旧账号播报状态。
- 这里的同步方法可以直接测试，异步方法主要服务 AstrBot 调用。
- SQLite 行对象通过 row_factory 转为 sqlite3.Row，便于按字段名读取。
- updated_at 统一使用秒级 Unix 时间戳，满足简单排序和排查需求。
"""
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

        # 内存索引映射，对 AstrBot 会话 ID、cf handle 与对应二元组分别构建映射，提升查询效率 
        self._bindings: dict[tuple[str, str], CodeforcesBinding] = {}   # (user_id, group_id) 为键
        self._group_index: dict[str, set[tuple[str, str]]] = {}         # AstrBot session/group_id 为键
        self._handle_index: dict[str, set[tuple[str, str]]] = {}        # handle 为键

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
            # WAL 允许读写更好地并发，适合机器人这种读多写少的小型本地数据库。
            self._conn.execute("PRAGMA journal_mode=WAL")
            # FULL 同步更保守，优先保证绑定数据在异常退出时不丢失。
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            self._conn.execute("PRAGMA wal_autocheckpoint=1000")

    def _init_schema(self) -> None:
        """表创建逻辑"""
        with self._lock:
            # uq_bind_group_handle 保证同一群内同一个 CF handle 不会被多人重复绑定。
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

                CREATE UNIQUE INDEX IF NOT EXISTS uq_bind_group_handle
                ON cf_bindings(group_id, cf_handle COLLATE NOCASE);
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
        """统一把 AstrBot/QQ ID 转成非空字符串。"""
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("user_id and session/group_id cannot be empty")
        return normalized

    @staticmethod
    def _normalize_handle(value: str) -> str:
        """统一清理 Codeforces handle，保留原大小写用于展示。"""
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
            # 重建缓存时所有索引都从同一批 binding 派生，避免索引间出现脏数据。
            self._cache_add(binding)

    def _cache_add(self, binding: CodeforcesBinding) -> None:
        """向内存索引添加单条记录，调用方需保证 key 不重复"""
        key = (binding.user_id, binding.group_id)
        self._bindings[key] = binding
        # 额外索引用 key 集合保存，避免复制完整 binding 对象导致同步复杂。
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

        # 删除主缓存后，需要同步清理 group 和 handle 两个二级索引。
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
            # 若绑定的是同一个 handle，则保留指纹；若切换账号，则重置指纹
            last_ac_fingerprint = (
                current.last_ac_fingerprint
                if current is not None and current.cf_handle.casefold() == cf_handle.casefold()
                else None
            )
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
            # INSERT ... ON CONFLICT 同时覆盖“首次绑定”和“更新绑定”两种情况。
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
                    updated_at = excluded.updated_at,
                    last_ac_fingerprint = excluded.last_ac_fingerprint
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
        """线程方法：通过 AstrBot 会话 ID 获取对应会话内所有的绑定信息"""
        group_id = self._normalize_id(group_id)
        with self._lock:
            # 获取键值对列表
            keys = self._group_index.get(group_id, set()).copy()
            # 锁内只复制当前快照，后续过滤和排序不继续持有数据库锁。
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

    def list_bindings(
        self,
        only_broadcast_enabled: bool = False,
    ) -> list[CodeforcesBinding]:
        """线程方法：获取所有绑定信息。"""
        with self._lock:
            bindings = list(self._bindings.values())

        if only_broadcast_enabled:
            bindings = [binding for binding in bindings if binding.enable_broadcast]
        return sorted(
            bindings,
            key=lambda binding: (
                binding.cf_handle.casefold(),
                binding.group_id,
                binding.user_id,
            ),
        )

    async def alist_bindings(
        self,
        only_broadcast_enabled: bool = False,
    ) -> list[CodeforcesBinding]:
        """异步 IO：获取所有绑定信息。"""
        return await asyncio.to_thread(
            self.list_bindings,
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
            
            # 先写数据库再写缓存，保证内存状态不会领先于持久化状态。
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

            # 指纹只用于自动播报去重，不参与唯一约束。
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
    
    def get_group_binding_by_handle(self, group_id, cf_handle):
        """线程方法：查询 cf handle 是否被唯一绑定"""
        group_id = self._normalize_id(group_id)
        handle_key = self._normalize_handle(cf_handle).casefold()
        with self._lock:
            keys = self._handle_index.get(handle_key, set()).copy()
            for key in keys:
                binding = self._bindings.get(key)
                # handle 索引是跨群的，因此还需要再判断 group_id。
                if binding is not None and binding.group_id == group_id:
                    return binding
        return None
    
    async def aget_group_binding_by_handle(
        self,
        group_id: str | int,
        cf_handle: str | int,
    ) -> CodeforcesBinding | None:
        """异步 IO：查询绑定唯一性"""
        return await asyncio.to_thread(
            self.get_group_binding_by_handle,
            group_id,
            cf_handle
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    async def aclose(self) -> None:
        """关闭数据库连接"""
        await asyncio.to_thread(self.close)
