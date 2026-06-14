# contests/models.py
"""比赛信息相关数据模型。"""
from dataclasses import dataclass

# 数据类：用于存放 codeforces.com 返回的比赛数据
@dataclass(slots=True)
class CodeforcesContestProfile:
    """Codeforces contest.list 返回的单场比赛资料。"""

    # 以下字段是 contest.list 中稳定存在、渲染卡片必须使用的核心字段。
    id: int
    name: str
    type: str
    phase: str
    frozen: bool
    duration_seconds: int
    # 以下字段在不同比赛类型中可能缺失，因此统一建模为可选字段。
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
    """比赛查询结果包装，统一承载成功状态、提示文本和比赛列表。"""

    ok: bool
    message: str
    contests: list[CodeforcesContestProfile] | None = None
