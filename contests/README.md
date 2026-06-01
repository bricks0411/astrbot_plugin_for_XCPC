## contest_info.py

#### 介绍

该模块实现 `codeforces.com` 的比赛信息推送，通过官方提供的 API 接口请求数据。

#### 模块实例化

在 `main.py` 中实例化为 `self.contest_info_handler`，初始化如下

```python
self.contest_info_handler = ContestInfoHandler()
```

#### 数据结构

规定模块返回的比赛信息模式

```python
# 数据类：用于存放 codeforces.com 返回的比赛数据
@dataclass(slots=True)
class CodeforcesContestProfile:
    id: int
    name: str
    type: str
    phase: str
    frozen: bool
    duration_seconds: int
    freeze_duration_seconds: int | None = None
    start_time_seconds: int | None = None
    relative_time_seconds: int | None = None
    prepared_by: str | None = None
    website_url: str | None = None
    description: str | None = None
    difficulty: int | None = None
    kind: str | None = None
    icpc_region: str | None = None
    country: str | None = None
    city: str | None = None
    season: str | None = None

# 数据类：返回给 main.py 的经过加工的消息数据
@dataclass(slots=True)
class CodeforcesContestInfoResult:
    ok: bool
    message: str
    contests: list[CodeforcesContestProfile] | None = None
```

#### 抽象接口

比赛信息查询

```python
async def ContestInfoRequest(
    self, 
    contest_number: int
) -> CodeforcesContestInfoResult | None:
    """查询比赛信息，并将加工后的消息返回给 main.py"""
```

