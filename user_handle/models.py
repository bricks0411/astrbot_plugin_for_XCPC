"""Codeforces 用户资料相关数据模型。"""
from dataclasses import dataclass

@dataclass(slots=True)
class CodeforcesUserProfile:
    """user.info 返回的单个用户资料。"""

    handle: str
    rank: str | None
    rating: int | None
    max_rank: str | None
    max_rating: int | None
    country: str | None
    city: str | None
    organization: str | None
    contribution: int | None
    friend_of_count: int | None
    avatar: str | None
    title_photo: str | None
    first_name: str | None
    last_name: str | None
    registration_time_seconds: int | None
    last_online_time_seconds: int | None

@dataclass(slots=True)
class CodeforcesUserInfoResult:
    """用户资料查询结果包装，统一承载成功状态、提示文本和资料对象。"""

    ok: bool
    message: str
    profile: CodeforcesUserProfile | None = None
