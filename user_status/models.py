# user_status/models.py
"""Codeforces 提交记录相关数据模型。"""
from dataclasses import dataclass


@dataclass(slots=True)
class CodeforcesMember:
    """提交作者队伍中的单个成员。"""

    handle: str
    name: str | None = None         # 返回数据中并不含此字段，可以删除


@dataclass(slots=True)
class CodeforcesParty:
    """Codeforces Submission.author 对象。"""

    # members 和 participantType 用于识别提交来源，ghost 表示是否为幽灵参赛者。
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
    """Codeforces Submission.problem 对象。"""

    # index/name/type/tags 是 problem 对象的基础字段，播报消息会直接使用。
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
    """Codeforces Submission 对象。"""

    # id 是全局唯一提交 ID，也是自动播报去重指纹的来源。
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
    """最新提交查询结果包装。"""

    ok: bool
    message: str
    latest_status: CodeforcesUserStatus | None = None
