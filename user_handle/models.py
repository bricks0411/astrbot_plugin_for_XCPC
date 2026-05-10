# user_handle/models.py
from dataclasses import dataclass

# 数据类：用于存放 codeforces.com 返回的用户数据
@dataclass(slots=True)
class CodeforcesUserProfile:
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

# 数据类：返回给 main.py 的经过加工的消息数据
@dataclass(slots=True)
class CodeforcesUserInfoResult:
    ok: bool
    message: str
    profile: CodeforcesUserProfile | None = None
