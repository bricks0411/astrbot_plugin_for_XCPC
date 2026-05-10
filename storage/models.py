# storage/models.py
from dataclasses import dataclass

# 数据类定义，规定返回数据格式
@dataclass(slots=True, frozen=True)
class CodeforcesBinding:
    user_id: str
    group_id: str
    cf_handle: str
    enable_broadcast: bool = True
    last_ac_fingerprint: str | None = None
    updated_at: int = 0