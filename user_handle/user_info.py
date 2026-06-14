# user_handle/user_info.py
"""
Codeforces 用户资料查询模块。

本模块封装 user.info 接口，只查询单个 handle，并把返回的 JSON 转为
CodeforcesUserProfile。外部命令和卡片渲染只依赖项目内模型，不直接依赖
Codeforces 原始字段名。

接口调用采用同步 requests + asyncio.to_thread 的组合：
- 同步函数集中处理网络异常、HTTP 异常和 JSON 格式异常。
- 异步入口负责把阻塞调用挪到线程中，保证机器人主循环可继续处理消息。

维护要点：
- user.info 使用 handles 参数，即使只查一个 handle 也会返回列表。
- handle 为空时直接返回失败结果，不访问远端接口。
- profile.handle 是必填字段，其它展示字段都可能缺失。
- titlePhoto 和 avatar 都原样保存，由卡片渲染器决定优先级。
- contribution、friendOfCount 等字段可能不存在，不应强制校验。
- HTTP 层成功不代表业务成功，仍需检查 payload.status。
- API 业务错误会通过 comment 返回，例如用户不存在。
- message 用于命令回显和日志，不在这里拼接卡片文案。
- _build_profile 只做字段映射，不做展示格式化。
- 新增用户字段时优先保持可选，避免旧账号数据缺字段时报错。
- requests 调用必须设置 User-Agent，减少被远端拒绝的概率。
- 这里的注释主要说明 user.info 的返回结构和容错边界。
"""
import asyncio
import requests
from .models import CodeforcesUserInfoResult, CodeforcesUserProfile


class UserInfoHandler:
    """负责获取并转换 Codeforces 用户资料。"""

    API_URL = "https://codeforces.com/api/user.info"
    REQUEST_TIMEOUT = 10
    USER_AGENT = "astrbot-plugin-for-xcpc/0.0.1"

    def __init__(self):
        pass

    def _build_profile(self, user_data: dict) -> CodeforcesUserProfile:
        """把 user.info 的单个用户对象转换为内部数据模型。"""
        return CodeforcesUserProfile(
            handle=user_data["handle"],
            rank=user_data.get("rank"),
            rating=user_data.get("rating"),
            max_rank=user_data.get("maxRank"),
            max_rating=user_data.get("maxRating"),
            country=user_data.get("country"),
            city=user_data.get("city"),
            organization=user_data.get("organization"),
            contribution=user_data.get("contribution"),
            friend_of_count=user_data.get("friendOfCount"),
            avatar=user_data.get("avatar"),
            title_photo=user_data.get("titlePhoto"),
            first_name=user_data.get("firstName"),
            last_name=user_data.get("lastName"),
            registration_time_seconds=user_data.get("registrationTimeSeconds"),
            last_online_time_seconds=user_data.get("lastOnlineTimeSeconds"),
        )

    def _request_user_info(self, user_handle: str) -> CodeforcesUserInfoResult:
        """线程方法：向 codeforces.com 发送请求并接收用户基本信息"""
        handle = user_handle.strip()
        # 若传入的 user_handle 为空，则抛出错误并返回对应信息
        # 这个 corner case 之前已经处理过，正常情况下，这一块不会执行
        if not handle:
            return CodeforcesUserInfoResult(
                ok=False,
                message="Codeforces handle cannot be empty.",
            )
        
        # 死了都要 try：主要承担 request 过程中可能发生的各种异常处理
        try:
            response = requests.get(
                self.API_URL,
                params={"handles": handle},
                timeout=self.REQUEST_TIMEOUT,
                headers={"User-Agent": self.USER_AGENT},
            )
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.Timeout:
            return CodeforcesUserInfoResult(
                ok=False,
                message="codeforces.com 没有在 10000ms 内返回数据，请求超时",
            )
        # request 异常捕获：使用 RequestException 基类捕获可能出现的所有异常，并将其统一为请求错误，并用 exc 展示
        except requests.exceptions.RequestException as exc:
            return CodeforcesUserInfoResult(
                ok=False,
                message=f"请求失败！异常类型: {exc}",
            )
        except ValueError:
            return CodeforcesUserInfoResult(
                ok=False,
                message="获取到非法 / 不被支持的 JSON 文件",
            )
        
        # 请求成功，但状态不 OK，则读取 comment 栏并返回 comment 中的错误信息
        if payload.get("status") != "OK":
            error_message = payload.get("comment", "Unknown Codeforces API error.")
            return CodeforcesUserInfoResult(
                ok=False,
                message=f"Codeforces API 请求出错: {error_message}",
            )
        
        # 服务商返回了一个空列表，或根本不是列表
        result = payload.get("result")
        if not isinstance(result, list) or not result:
            return CodeforcesUserInfoResult(
                ok=False,
                message="收到 Codeforces 返回的空列表 / 非列表文件",
            )

        # 返回数据中没有 handle 栏
        user_data = result[0]
        if "handle" not in user_data:
            return CodeforcesUserInfoResult(
                ok=False,
                message="返回数据缺少 handle 字段",
            )

        # 通过所有合法性检查，构建返回结构体
        profile = self._build_profile(user_data)
        summary = (
            f"handle: {profile.handle}\n"
            f"rating: {profile.rating}\n"
            f"maxRating: {profile.max_rating}\n"
            f"rank: {profile.rank}\n"
            f"maxRank: {profile.max_rank}"
        )
        return CodeforcesUserInfoResult(
            ok=True,
            message=summary,
            profile=profile,
        )

    async def UserInfoRequest(self, user_handle: str) -> CodeforcesUserInfoResult:
        """根据给定 handle 查询用户信息"""
        # 创建单独线程，将 _request_user_info 放到线程池线程中执行，避免阻塞事件循环
        return await asyncio.to_thread(self._request_user_info, user_handle)
