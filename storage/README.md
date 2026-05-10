## user_db.py

#### 介绍

该模块实现数据的可持久化存储逻辑，`sqlite3` 作为数据库存储数据。

通过异步 IO + 线程池，对每个请求都分配一个线程进行并行化修改。

引入写锁避免发生写冲突，在线程方法中优先修改数据库，同时采用 WAL 预写日志策略以保证数据安全。

模块注重线程安全和冲突避免，适合日常中小型并发场景，并发量过大时可能会出现线程池枯竭、请求积压等情况，但可以满足一般的 QQ 群场景。

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
	"""通过群号获取本群绑定信息列表"""
```

```python
async def afind_by_handle(
    self, 
    cf_handle: str
) -> list[CodeforcesBinding]
	 """通过 handle 获取用户绑定信息列表"""
```



