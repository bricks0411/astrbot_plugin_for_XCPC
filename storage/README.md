## user_db.py

#### 介绍

该模块实现数据的可持久化存储逻辑，`sqlite3` 作为数据库存储数据。

通过异步 IO + 线程池，对每个请求都分配一个线程进行并行化修改。

引入写锁避免发生写冲突，在线程方法中优先修改数据库，同时采用 WAL 预写日志策略以保证数据安全。

模块注重线程安全和冲突避免，适合日常中小型并发场景，并发量过大时可能会出现线程池枯竭、请求积压等情况，但可以满足一般的 QQ 群场景。

#### 模块实例化

在 `main.py` 中实例化为 `self.user_db_handler`，初始化如下
```python
self.user_db_handler = DataStorageHandler(db_path=self._build_user_db_path())
```

#### 数据结构

规定模块返回的用户信息模式

```python
# 数据类定义，规定用户绑定信息
@dataclass(slots=True, frozen=True)
class CodeforcesBinding:
    user_id: str
    group_id: str
    cf_handle: str
    enable_broadcast: bool = True
    last_ac_fingerprint: str | None = None
    updated_at: int = 0
```

`group_id` 是沿用的字段名，当前实际存储 AstrBot 的完整会话 ID，即 `event.unified_msg_origin`。该值可直接用于自动推送时调用 `context.send_message()`，不再保存纯数字群号。

在内存维护一份数据库备份

```python
self._bindings: dict[tuple[str, str], CodeforcesBinding] = {}   # (user_id, session_id) 为键
self._group_index: dict[str, set[tuple[str, str]]] = {}         # session_id 为键
"""
{
	session_id: {
		(user_id, session_id),
		(user_id, session_id),
		...
	}
}
"""
self._handle_index: dict[str, set[tuple[str, str]]] = {}        # handle 为键
"""
{
    cf_handle: {
        (user_id, session_id),
        (user_id, session_id),
        ...
    }
}
"""
```

#### 抽象接口

**数据加载**

```python
async def areload_cache(self) -> None
	"""从数据库中加载所有数据至内存"""
```

**数据修改**

```python
async def abind_user(
    self,
    user_id: str | int,
    group_id: str | int,
    cf_handle: str,
    enable_broadcast: bool | None = None,
) -> CodeforcesBinding
	"""执行用户绑定操作"""
```

```python
async def aunbind_user(
    self, 
    user_id: str | int, 
    group_id: str | int
) -> bool
	"""执行用户解绑操作"""
```

```python
async def aset_broadcast_enabled(
    self, 
    user_id: str | int,
    group_id: str | int,
    enabled: bool,
) -> CodeforcesBinding | None
	"""修改用户 enable 字段"""
```

```python
async def aupdate_last_ac_fingerprint(
    self,
    user_id: str | int,
    group_id: str | int,
    fingerprint: str | None,
) -> CodeforcesBinding | None
	"""更新指定用户的记录指纹"""
```

**数据查询**

```python
async def aget_binding(
    self,
    user_id: str | int,
    group_id: str | int,
) -> CodeforcesBinding | None
	"""执行用户查询操作"""
```

```python
async def alist_group_bindings(
    self,
    group_id: str | int,
    only_broadcast_enabled: bool = False,
) -> list[CodeforcesBinding]
	"""通过 AstrBot 会话 ID 获取该会话绑定信息列表"""
```

```python
async def alist_bindings(
    self,
    only_broadcast_enabled: bool = False,
) -> list[CodeforcesBinding]
	"""获取所有绑定信息列表，可按是否开启播报过滤"""
```

```python
async def afind_by_handle(
    self, 
    cf_handle: str
) -> list[CodeforcesBinding]
	 """通过 handle 获取用户绑定信息列表"""
```

#### 自动化推送相关说明

`automation.auto_push.AutomationPushHandler` 会通过 `alist_bindings(only_broadcast_enabled=True)` 获取所有允许播报的绑定记录。

该接口是公开查询入口，用于替代直接访问 `_bindings`、`_group_index`、`_handle_index` 等内部缓存字段，避免外部模块绕过锁和封装。

自动化播报会直接使用 `CodeforcesBinding.group_id` 作为发送目标，因此写入绑定时必须传入 AstrBot 的完整会话 ID。`main.py` 中使用 `event.unified_msg_origin` 作为该字段的来源。



