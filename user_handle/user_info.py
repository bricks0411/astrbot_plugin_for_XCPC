"""Codeforces user.info 查询。"""
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
        if not handle:
            return CodeforcesUserInfoResult(
                ok=False,
                message="Codeforces handle cannot be empty.",
            )
        
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
        
        if payload.get("status") != "OK":
            error_message = payload.get("comment", "Unknown Codeforces API error.")
            return CodeforcesUserInfoResult(
                ok=False,
                message=f"Codeforces API 请求出错: {error_message}",
            )
        
        result = payload.get("result")
        if not isinstance(result, list) or not result:
            return CodeforcesUserInfoResult(
                ok=False,
                message="收到 Codeforces 返回的空列表 / 非列表文件",
            )

        user_data = result[0]
        if "handle" not in user_data:
            return CodeforcesUserInfoResult(
                ok=False,
                message="返回数据缺少 handle 字段",
            )

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
        return await asyncio.to_thread(self._request_user_info, user_handle)
