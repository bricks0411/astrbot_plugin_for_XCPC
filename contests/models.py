"""比赛信息相关数据模型。"""
from dataclasses import dataclass

@dataclass(slots=True)
class CodeforcesContestProfile:
    """Codeforces contest.list 返回的单场比赛资料。"""

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

@dataclass(slots=True)
class CodeforcesContestInfoResult:
    """比赛查询结果包装，统一承载成功状态、提示文本和比赛列表。"""

    ok: bool
    message: str
    contests: list[CodeforcesContestProfile] | None = None
