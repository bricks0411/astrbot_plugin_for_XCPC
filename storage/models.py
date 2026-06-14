# storage/models.py
"""本地用户绑定记录数据模型。"""
from dataclasses import dataclass

# 数据类定义，规定返回数据格式
@dataclass(slots=True, frozen=True)
class CodeforcesBinding:
    """QQ 用户在某个 AstrBot 会话中的 Codeforces 绑定信息。"""

    # user_id 和 group_id 共同定位一条绑定记录。
    user_id: str
    group_id: str
    cf_handle: str
    # enable_broadcast 控制是否自动播报该绑定用户的新 AC。
    enable_broadcast: bool = True
    # last_ac_fingerprint 记录已播报/基线提交，避免重复推送历史 AC。
    last_ac_fingerprint: str | None = None
    updated_at: int = 0
