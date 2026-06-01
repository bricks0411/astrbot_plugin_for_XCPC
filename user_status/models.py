# user_status/models.py
from dataclasses import dataclass


@dataclass(slots=True)
class CodeforcesMember:
    handle: str
    name: str | None = None         # 返回数据中并不含此字段，可以删除


@dataclass(slots=True)
class CodeforcesParty:
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
    ok: bool
    message: str
    latest_status: CodeforcesUserStatus | None = None
