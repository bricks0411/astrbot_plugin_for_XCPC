# contests/contest_info.py
"""
Codeforces 比赛列表查询模块。

这里封装 contest.list 接口：
- 同步函数负责真实 HTTP 请求、状态码检查和 JSON 结构校验。
- 异步入口通过 asyncio.to_thread 调用同步函数，避免阻塞 AstrBot 事件循环。
- 返回值始终是项目内定义的结果对象，调用方不需要直接处理 requests 异常。

接口数据来自外部服务，因此解析时采用“必填字段严格校验、可选字段宽松读取”的策略。
这样既能尽早发现 Codeforces 返回格式变化，也能允许不同类型比赛缺少扩展字段。

维护要点：
- contest_number 只影响最终截断数量，不影响远端接口返回总量。
- gym=false 用于排除 Gym 比赛，保持推送内容更贴近日常 CF 赛事。
- response.raise_for_status 只处理 HTTP 层错误，API 层错误还要看 status。
- payload 必须是 dict，否则说明返回体不是预期 API 响应。
- result 必须是非空 list，否则调用方没有可展示的数据。
- required_fields 是构造基础比赛卡片所需的最小字段集合。
- 可选字段直接使用 get，避免少数字段缺失导致整次查询失败。
- _build_profile 不做复杂判断，只把已校验字段映射到数据类。
- HTTP 超时、请求异常和 JSON 解析异常都转换为业务结果对象。
- 调用方通过 ok 字段判断是否展示 contests。
- message 同时用于日志、命令文本回退和比赛卡片摘要。
- 新增展示字段时，先在模型里添加可选字段，再在渲染器中消费。
- 不要在这里构造用户可见长文本，文本格式化属于 automation 或 card 模块。
- 不要直接在异步入口里调用 requests，必须保持 to_thread 包装。
- 如果 Codeforces 限流返回 FAILED，也会落到 status != OK 分支。
- 这里的注释主要说明远端协议边界和错误归一化策略。
"""
import asyncio
import requests
from .models import CodeforcesContestInfoResult, CodeforcesContestProfile

class ContestInfoHandler:
    """负责获取并转换 Codeforces 比赛列表。"""

    API_URL = "https://codeforces.com/api/contest.list"
    REQUEST_TIMEOUT = 10

    def __init__(self):
        pass

    def _build_profile(self, contest_data: dict) -> CodeforcesContestProfile:
        """把单个 contest JSON 对象转换为内部数据模型。"""
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
        # requests 是同步库，调用方会把本方法放到线程中执行。
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
            # Codeforces API 业务失败通常放在 comment 字段里，而不是 HTTP 状态码里。
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
            # 列表元素必须是对象，否则后续字段读取没有可靠语义。
            if not isinstance(contest_data, dict):
                return CodeforcesContestInfoResult(
                    ok=False,
                    message="Codeforces 返回了不被支持的文件格式",
                    contests=None,
                )

            missing_fields = required_fields - contest_data.keys()
            if missing_fields:
                # 必填字段缺失说明接口结构已经不符合当前模型，直接返回错误。
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
        # 创建使用 _request_contest_info 方法的线程，避免同步 HTTP 阻塞事件循环。
        return await asyncio.to_thread(self._request_contest_info, contest_number)
