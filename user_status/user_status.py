"""
Codeforces 最新提交查询模块。

本模块封装 user.status 接口，并固定只请求最新一条提交记录。
自动播报只需要判断“是否出现新的 AC”，因此不拉取完整提交历史，避免接口压力。

Codeforces Submission 对象是多层嵌套结构：
- author 对应 Party。
- author.members 对应 Member 列表。
- problem 对应 Problem。
- 顶层对象包含提交时间、判题结果、资源消耗等信息。

解析逻辑会严格校验必填字段，对可能缺失的 contestId、verdict、rating 等字段
统一使用 optional helper 处理，防止 None/缺字段导致后台任务异常退出。

维护要点：
- LATEST_SUBMISSION_COUNT 固定为 1，避免自动轮询拉取过多历史数据。
- UserStatusRequest 是异步入口，外部模块不应直接调用同步请求函数。
- _request_user_status 只负责请求和解析，不做播报去重判断。
- ok=False 表示请求或协议层失败，调用方应记录日志后跳过。
- latest_status=None 表示用户没有提交记录，不是异常。
- verdict 可能为空，例如正在判题中的提交。
- contestId 可能为空，例如题库或特殊来源的提交。
- problem.rating 可能为空，播报时需要展示“未知”。
- Submission.id 是自动播报去重最可靠的字段。
- author.members 虽然通常只有一个成员，但模型保留列表结构。
- ghost 字段必须是 bool，不能把 0/1 当作有效布尔替代。
- relativeTimeSeconds、passedTestCount 等字段用严格 int 校验。
- optional helper 负责吸收 Codeforces 返回中的缺失或类型不符字段。
- 请求超时、HTTP 错误和 JSON 解析错误都会转成结果对象。
- 解析异常不向外抛出，避免后台轮询任务被单条脏数据打断。
- 新增 Submission 字段时，先判断它是必填还是可选。
- 这里的注释主要说明 Codeforces 数据结构和容错边界。
"""
import asyncio
from typing import Any

import requests

from .models import (
    CodeforcesMember,
    CodeforcesParty,
    CodeforcesProblem,
    CodeforcesUserStatus,
    CodeforcesUserStatusResult,
)


class UserStatusHandler:
    """负责获取并转换 Codeforces 用户最新提交记录。"""

    API_URL = "https://codeforces.com/api/user.status"
    REQUEST_TIMEOUT = 10
    LATEST_SUBMISSION_COUNT = 1
    USER_AGENT = "astrbot-plugin-for-xcpc/0.0.1"

    def __init__(self):
        pass

    def _build_member(self, member_data: dict[str, Any]) -> CodeforcesMember:
        """构造 Party.members 中的单个成员信息"""
        handle = member_data.get("handle")
        if not isinstance(handle, str) or not handle:
            raise ValueError("member is missing required field: handle")

        # Codeforces 官方 Member 对象有 name 字段，但 user.status 通常不会返回
        name = member_data.get("name")
        return CodeforcesMember(
            handle=handle,
            name=name if isinstance(name, str) else None,
        )

    def _build_party(self, party_data: dict[str, Any]) -> CodeforcesParty:
        """构造提交记录中的 author 字段，对应 Codeforces Party 对象"""
        # author.members 是嵌套列表，必须先校验类型再逐项转换。
        members_data = party_data.get("members")
        if not isinstance(members_data, list):
            raise ValueError("author is missing required field: members")

        participant_type = party_data.get("participantType")
        if not isinstance(participant_type, str):
            raise ValueError("author is missing required field: participantType")

        ghost = party_data.get("ghost")
        if not isinstance(ghost, bool):
            raise ValueError("author is missing required field: ghost")

        # members 是嵌套对象列表，需要逐个转换成 CodeforcesMember
        members = []
        for member in members_data:
            if not isinstance(member, dict):
                raise ValueError("author member item must be an object")
            members.append(self._build_member(member))

        return CodeforcesParty(
            members=members,
            participantType=participant_type,
            ghost=ghost,
            contestId=self._optional_int(party_data.get("contestId")),
            teamId=self._optional_int(party_data.get("teamId")),
            teamName=self._optional_str(party_data.get("teamName")),
            room=self._optional_int(party_data.get("room")),
            startTimeSeconds=self._optional_int(party_data.get("startTimeSeconds")),
        )

    def _build_problem(self, problem_data: dict[str, Any]) -> CodeforcesProblem:
        """构造提交记录中的 problem 字段，对应 Codeforces Problem 对象"""
        # problem 的 index/name/type/tags 是展示播报消息所需的核心字段。
        index = problem_data.get("index")
        if not isinstance(index, str):
            raise ValueError("problem is missing required field: index")

        name = problem_data.get("name")
        if not isinstance(name, str):
            raise ValueError("problem is missing required field: name")

        problem_type = problem_data.get("type")
        if not isinstance(problem_type, str):
            raise ValueError("problem is missing required field: type")

        tags = problem_data.get("tags")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError("problem field tags must be a list of strings")

        return CodeforcesProblem(
            index=index,
            name=name,
            type=problem_type,
            tags=tags,
            contestId=self._optional_int(problem_data.get("contestId")),
            problemsetName=self._optional_str(problem_data.get("problemsetName")),
            points=self._optional_float(problem_data.get("points")),
            rating=self._optional_int(problem_data.get("rating")),
        )

    def _build_status(self, status_data: dict[str, Any]) -> CodeforcesUserStatus:
        """构造单条提交记录，对应 Codeforces Submission 对象"""
        # 这些字段在 Submission 对象中应当始终存在，缺失时说明返回数据不完整
        required_int_fields = [
            "id",
            "creationTimeSeconds",
            "relativeTimeSeconds",
            "passedTestCount",
            "timeConsumedMillis",
            "memoryConsumedBytes",
        ]
        for field_name in required_int_fields:
            # bool 在 Python 中是 int 子类，这里用 _is_int 排除 True/False。
            if not self._is_int(status_data.get(field_name)):
                raise ValueError(f"submission is missing required field: {field_name}")

        problem = status_data.get("problem")
        if not isinstance(problem, dict):
            raise ValueError("submission is missing required field: problem")

        author = status_data.get("author")
        if not isinstance(author, dict):
            raise ValueError("submission is missing required field: author")

        programming_language = status_data.get("programmingLanguage")
        if not isinstance(programming_language, str):
            raise ValueError("submission is missing required field: programmingLanguage")

        testset = status_data.get("testset")
        if not isinstance(testset, str):
            raise ValueError("submission is missing required field: testset")

        # contestId / verdict / points 属于可能缺失的字段，统一通过 _optional_* 处理
        return CodeforcesUserStatus(
            id=status_data["id"],
            creationTimeSeconds=status_data["creationTimeSeconds"],
            relativeTimeSeconds=status_data["relativeTimeSeconds"],
            problem=self._build_problem(problem),
            author=self._build_party(author),
            programmingLanguage=programming_language,
            testset=testset,
            passedTestCount=status_data["passedTestCount"],
            timeConsumedMillis=status_data["timeConsumedMillis"],
            memoryConsumedBytes=status_data["memoryConsumedBytes"],
            contestId=self._optional_int(status_data.get("contestId")),
            verdict=self._optional_str(status_data.get("verdict")),
            points=self._optional_float(status_data.get("points")),
        )

    def _request_user_status(self, user_handle: str) -> CodeforcesUserStatusResult:
        """线程方法：向 codeforces.com 请求指定用户的最新一条提交记录"""
        # 调用方正常情况下会传入字符串，这里额外兜底，避免错误参数导致线程内异常
        if not isinstance(user_handle, str):
            return CodeforcesUserStatusResult(
                ok=False,
                message="Codeforces handle must be a string.",
            )

        handle = user_handle.strip()
        if not handle:
            return CodeforcesUserStatusResult(
                ok=False,
                message="Codeforces handle cannot be empty.",
            )

        # 指纹级更新只需要最新一条提交，因此固定 count=1
        params: dict[str, str] = {
            "handle": handle,
            "count": str(self.LATEST_SUBMISSION_COUNT),
        }

        # 请求 Codeforces API，并处理网络、超时、HTTP、JSON 解析等异常
        try:
            response = requests.get(
                self.API_URL,
                params=params,
                timeout=self.REQUEST_TIMEOUT,
                headers={"User-Agent": self.USER_AGENT},
            )
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.Timeout:
            return CodeforcesUserStatusResult(
                ok=False,
                message="Codeforces.com 没有在 10000ms 内返回数据，请求超时。",
            )
        except requests.exceptions.RequestException as exc:
            return CodeforcesUserStatusResult(
                ok=False,
                message=f"请求 Codeforces 失败：{exc}",
            )
        except ValueError:
            return CodeforcesUserStatusResult(
                ok=False,
                message="Codeforces 返回了非法 JSON。",
            )

        # Codeforces 正常返回时，payload 应当是包含 status/result 的字典
        if not isinstance(payload, dict):
            return CodeforcesUserStatusResult(
                ok=False,
                message="Codeforces 返回了不支持的响应格式。",
            )

        # API 层面的失败不会一定表现为 HTTP 错误，需要读取 status/comment
        if payload.get("status") != "OK":
            error_message = payload.get("comment", "Unknown Codeforces API error.")
            return CodeforcesUserStatusResult(
                ok=False,
                message=f"Codeforces API 请求出错：{error_message}",
            )

        # user.status 的 result 应当是提交记录列表；count = 1 时最多只有一条
        result = payload.get("result")
        if not isinstance(result, list):
            return CodeforcesUserStatusResult(
                ok=False,
                message="Codeforces 返回的 result 字段不是列表。",
            )

        # 将原始 JSON 列表转换为项目内定义的数据类，字段异常时返回错误结果
        try:
            statuses = []
            for item in result:
                # Codeforces result 应为提交对象列表，非对象元素直接视为协议异常。
                if not isinstance(item, dict):
                    raise ValueError("submission item must be an object")
                statuses.append(self._build_status(item))
        except ValueError as exc:
            return CodeforcesUserStatusResult(
                ok=False,
                message=f"Codeforces 返回了不完整或无效的数据：{exc}",
            )
        
        if not statuses:
            return CodeforcesUserStatusResult(
                ok=True,
                message=f"用户 {handle} 没有任何提交记录。",
            )

        return CodeforcesUserStatusResult(
            ok=True,
            message=f"获取到用户 {handle} 的最新提交信息。",
            latest_status=statuses[0],
        )

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        """读取可选整数字段，bool 在 Python 中是 int 子类，需要排除"""
        return value if UserStatusHandler._is_int(value) else None

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        """读取可选数字字段，例如 problem.points 或 submission.points"""
        return value if isinstance(value, int | float) and not isinstance(value, bool) else None

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        """读取可选字符串字段，缺失或类型不符时返回 None"""
        return value if isinstance(value, str) else None

    @staticmethod
    def _is_int(value: Any) -> bool:
        """判断值是否为真正的整数，避免把 True / False 当作 1 / 0"""
        return isinstance(value, int) and not isinstance(value, bool)

    async def UserStatusRequest(self, user_handle: str) -> CodeforcesUserStatusResult:
        """创建线程，查询指定用户最新一条提交记录，避免阻塞事件循环"""
        # 自动推送任务会频繁调用该入口，所以必须避免同步请求卡住事件循环。
        return await asyncio.to_thread(self._request_user_status, user_handle)
