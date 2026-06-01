# contests/contest_info.py
import asyncio
import requests
from .models import CodeforcesContestInfoResult, CodeforcesContestProfile

class ContestInfoHandler:
    API_URL = "https://codeforces.com/api/contest.list"
    REQUEST_TIMEOUT = 10

    def __init__(self):
        pass

    def _build_profile(self, contest_data: dict) -> CodeforcesContestProfile:
        return CodeforcesContestProfile(
            id=contest_data["id"],
            name=contest_data["name"],
            type=contest_data["type"],
            phase=contest_data["phase"],
            frozen=contest_data["frozen"],
            duration_seconds=contest_data["durationSeconds"],
            freeze_duration_seconds=contest_data.get("freezeDurationSeconds"),
            start_time_seconds=contest_data.get("startTimeSeconds"),
            relative_time_seconds=contest_data.get("relativeTimeSeconds"),
            prepared_by=contest_data.get("preparedBy"),
            website_url=contest_data.get("websiteUrl"),
            description=contest_data.get("description"),
            difficulty=contest_data.get("difficulty"),
            kind=contest_data.get("kind"),
            icpc_region=contest_data.get("icpcRegion"),
            country=contest_data.get("country"),
            city=contest_data.get("city"),
            season=contest_data.get("season"),
        )
    
    def _request_contest_info(self, contest_number: int) -> CodeforcesContestInfoResult:
        """线程方法：向 codeforces.com 发送请求并接收数据"""
        try:
            response = requests.get(
                self.API_URL,
                params={"gym": "false"},
                timeout=self.REQUEST_TIMEOUT,
                headers={"User-Agent": "astrbot-plugin-for-xcpc/0.0.1"},
            )
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.Timeout:
            return CodeforcesContestInfoResult(
                ok=False,
                message="Codeforces.com 没有在 10000ms 内返回数据，请求超时",
                contests=None,
            )
        except requests.exceptions.RequestException as exc:
            return CodeforcesContestInfoResult(
                ok=False,
                message=f"请求失败！异常类型: {exc}",
                contests=None,
            )
        except ValueError:
            return CodeforcesContestInfoResult(
                ok=False,
                message="获取到非法 / 不被支持的 json 文件",
                contests=None,
            )
        
        if not isinstance(payload, dict):
            return CodeforcesContestInfoResult(
                ok=False,
                message="Codeforces 返回了不被支持的 json 格式",
                contests=None,
            )

        if payload.get("status") != "OK":
            error_message = payload.get("comment", "Codeforces API 出现未知错误")
            return CodeforcesContestInfoResult(
                ok=False,
                message=f"Codeforces API 请求出错: {error_message}",
                contests=None,
            )
        
        result = payload.get("result")
        if not isinstance(result, list) or not result:
            return CodeforcesContestInfoResult(
                ok=False,
                message="收到 Codeforces 返回的空列表",
                contests=None
            )

        contests: list[CodeforcesContestProfile] = []
        required_fields = {
            "id",
            "name",
            "type",
            "phase",
            "frozen",
            "durationSeconds",
        }

        for contest_data in result:
            if not isinstance(contest_data, dict):
                return CodeforcesContestInfoResult(
                    ok=False,
                    message="Codeforces 返回了不被支持的文件格式",
                    contests=None,
                )

            missing_fields = required_fields - contest_data.keys()
            if missing_fields:
                missing_text = ", ".join(sorted(missing_fields))
                return CodeforcesContestInfoResult(
                    ok=False,
                    message=f"返回数据缺失字段: {missing_text}",
                    contests=None,
                )
            
            contests.append(self._build_profile(contest_data))

        result_contest_data: list[CodeforcesContestProfile] = []
        for i in range(0, min(contest_number, len(contests))):
            result_contest_data.append(contests[i])

        return CodeforcesContestInfoResult(
            ok=True,
            message=f"从 codeforces.com 获取到 {len(contests)} 条比赛数据，截断至 {contest_number} 条",
            contests=result_contest_data,
        )

    async def ContestInfoRequest(self, contest_number: int) -> CodeforcesContestInfoResult | None:
        """查询比赛信息，并将加工后的消息返回给 main.py"""
        # 创建使用 _request_contest_info 方法的线程
        return await asyncio.to_thread(self._request_contest_info, contest_number)
