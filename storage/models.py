"""本地用户绑定记录数据模型。"""
from dataclasses import dataclass

@dataclass(slots=True, frozen=True)
class CodeforcesBinding:
    """QQ 用户在某个 AstrBot 会话中的 Codeforces 绑定信息。"""

    user_id: str
    group_id: str
    cf_handle: str
    enable_broadcast: bool = True
    last_ac_fingerprint: str | None = None
    updated_at: int = 0
