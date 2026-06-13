## user_status.py

#### 介绍

该模块实现 `codeforces` 用户提交记录的查询功能。

#### 模块实例化

在 `main.py` 中实例化为 `user_status_handler`，初始化如下

```python
self.user_status_handler = UserStatusHandler()
```

#### 数据结构

规定模块返回的比赛信息模式

```python
@dataclass(slots=True)
class CodeforcesMember:
    handle: str
    name: str | None = None         # 返回数据中并不含此字段，可以删除

@dataclass(slots=True)
class CodeforcesParty:
    members: list[CodeforcesMember]
    participantType: str
    ghost: bool
    contestId: int | None = None
    teamId: int | None = None
    teamName: str | None = None
    room: int | None = None
    startTimeSeconds: int | None = None

@dataclass(slots=True)
class CodeforcesProblem:
    index: str
    name: str
    type: str
    tags: list[str]
    contestId: int | None = None
    problemsetName: str | None = None
    points: float | None = None
    rating: int | None = None

@dataclass(slots=True)
class CodeforcesUserStatus:
    id: int
    creationTimeSeconds: int
    relativeTimeSeconds: int
    problem: CodeforcesProblem
    author: CodeforcesParty
    programmingLanguage: str
    testset: str
    passedTestCount: int
    timeConsumedMillis: int
    memoryConsumedBytes: int
    contestId: int | None = None
    verdict: str | None = None
    points: float | None = None

@dataclass(slots=True)
class CodeforcesUserStatusResult:
    ok: bool
    message: str
    latest_status: CodeforcesUserStatus | None = None
```

#### 抽象接口

用户提交信息查询

```python
async def UserStatusRequest(
    self, 
    user_handle: str
) -> CodeforcesUserStatusResult:
    """查询指定用户最新一条提交记录"""
```

