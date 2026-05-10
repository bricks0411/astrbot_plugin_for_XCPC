# contests/models.py
from dataclasses import dataclass

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
