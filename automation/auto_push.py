# automation/auto_push.py
"""
自动推送调度模块。

本模块维护两个长期后台任务：
1. 比赛信息推送任务，按配置的每日时间触发。
2. 提交记录轮询任务，按 loop_time 周期触发。

两个任务共享同一个 Codeforces API 节流器，避免 contest.list 和
user.status 在短时间内连续命中 Codeforces 的接口限制。
模块本身不直接依赖 AstrBot 事件对象，所有发送动作都通过回调注入。
这样可以把“调度/查询/消息组装”和“平台消息发送”拆开，方便测试和维护。

维护要点：
- start 只负责创建后台任务，不在当前协程中直接执行长期循环。
- stop 会先关闭运行标志，再 cancel task，最后等待任务收尾。
- 比赛推送按每日固定时刻运行，错过当天时刻则顺延到第二天。
- 提交轮询按 loop_time 周期运行，轮询开始时间会受 API 节流影响。
- Codeforces API 失败通常返回 ok=False，只有网络/代码异常才进入 except。
- 单个 handle 查询失败不会终止整个提交轮询任务。
- API_REQUEST_INTERVAL_SECONDS 是自动任务共享的请求间隔。
- _api_request_lock 只保护请求开始时间，不保护后续消息发送。
- 消息发送失败只影响当前绑定，不应影响后续绑定处理。
- 首次轮询看到 AC 时只写入基线，不播报历史提交。
- 首次轮询看到非 AC 时写 baseline，避免下一条 AC 被误判为旧记录。
- 指纹优先使用 Codeforces submission id，因为它全局唯一且稳定。
- 同一 handle 多群绑定时 API 只请求一次，再对绑定列表分发。
- build_contest_message 是比赛图片渲染失败时的文本兜底。
- 自动任务的日志要能反映下一次运行时间，便于排查调度问题。
- 任务取消必须重新抛出 CancelledError，避免插件关闭时卡住。
- enable_getter 由 main.py 注入，保证开关状态读取的是最新值。
- contest_message_sender 可选，缺失时回退为纯文本发送。
- 该模块不直接读写配置，只消费初始化时注入的配置值。
- 新增 Codeforces API 调用时必须先进入 _wait_for_api_request_slot。
- 不要在循环末尾随意 sleep 代替统一节流，否则并行任务仍可能撞车。
- 这里的注释主要说明并发、重试和去重边界。
- 比赛任务和提交任务生命周期彼此独立，只共享 API 请求节流状态。
- 任务运行标志用于自然退出，cancel 用于打断当前 sleep 或等待。
- 循环外部不要捕获 BaseException，否则会吞掉取消信号。
- 发送到多个群时，比赛 API 只查一次，结果复用到所有目标会话。
- 提交播报更新指纹必须在消息发送成功后执行。
- 如果发送失败，不更新指纹，下一轮仍有机会重试播报。
- loop_time 过小也不会突破 API_REQUEST_INTERVAL_SECONDS 的请求间隔。
- 这里不直接处理手动 /cf 或 /比赛 命令，那些属于 main.py。
"""
import asyncio
import datetime
import re
import time
from collections.abc import Awaitable, Callable

from astrbot.api import logger

class AutomationPushHandler:
    """
    自动化推送任务调度器
    本模块不直接依赖 AstrBot API，自动化任务只生成纯文本消息
    具体发送动作通过 main.py 注入的 message_sender 回调完成
    """

    API_REQUEST_INTERVAL_SECONDS = 3
    CONTEST_RETRY_SECONDS = 60

    def __init__(
        self,
        *,
        user_status_handler,
        contest_info_handler,
        user_db_handler,
        loop_time: int,
        enable_getter: Callable[[], bool],
        message_sender: Callable[[str, str], Awaitable[None]],
        contest_message_sender: Callable[[str, object, str], Awaitable[None]] | None = None,
        contest_number: int,
        contest_push_time: str,
        contest_push_sessions: list[str],
    ) -> None:
        self.user_status_handler = user_status_handler
        self.contest_info_handler = contest_info_handler
        self.user_db_handler = user_db_handler
        self.loop_time = loop_time
        self.enable_getter = enable_getter
        # main.py 注入的发送回调，签名为 (session_id, message) -> awaitable
        self.message_sender = message_sender
        self.contest_message_sender = contest_message_sender
        self.contest_number = contest_number
        self.contest_push_time = contest_push_time
        self.contest_push_sessions = contest_push_sessions

        self.hour_contest = 0
        self.minute_contest = 0
        self._contest_push_running = True
        self._submission_push_running = True
        self._contest_scheduler_task: asyncio.Task | None = None
        self._submission_scheduler_task: asyncio.Task | None = None
        # 两个自动任务都会请求 Codeforces，因此用同一把锁串行化请求起点。
        self._api_request_lock = asyncio.Lock()
        # 记录上一次 API 请求的开始时间，而不是结束时间，避免网络慢时过度等待。
        self._last_api_request_time: float | None = None

        self._configure_contest_push()

    async def start(self) -> None:
        """启动自动化推送任务"""
        # 比赛推送依赖明确的推送时间和目标会话，只有在时间和目标会话都存在时才创建后台任务
        if self._contest_push_running and self.contest_push_sessions:
            self._contest_scheduler_task = asyncio.create_task(
                self._auto_time_scheduler_contest()
            )
            self._log_next_contest_run()
            logger.info("比赛自动推送任务已启动")
        elif self._contest_push_running:
            logger.info("未配置比赛推送会话，跳过比赛自动推送任务")

        # 提交轮询依赖绑定数据；没有绑定时任务仍会存活，只是每轮查到空列表
        if self._submission_push_running:
            self._submission_scheduler_task = asyncio.create_task(
                self._auto_time_scheduler_submission()
            )
            self._log_next_submission_run(datetime.datetime.now())
            logger.info("提交记录自动轮询任务已启动")

    async def stop(self) -> None:
        """停止自动化推送任务"""
        self._contest_push_running = False
        self._submission_push_running = False
        logger.info("正在停止自动化推送任务")
        tasks = []
        if self._contest_scheduler_task:
            self._contest_scheduler_task.cancel()
            tasks.append(self._contest_scheduler_task)
        if self._submission_scheduler_task:
            self._submission_scheduler_task.cancel()
            tasks.append(self._submission_scheduler_task)
        if tasks:
            # 等待任务响应 cancel，避免数据库连接先关闭而后台任务仍在写状态
            await asyncio.gather(*tasks, return_exceptions=True)

    def _configure_contest_push(self) -> None:
        """校验并初始化比赛定时推送配置"""
        if not self.contest_push_time:
            logger.info("未设置比赛推送时间，跳过")
            self._contest_push_running = False
            return

        if not self._validate_time(self.contest_push_time):
            logger.warning("时间格式错误，跳过比赛推送配置")
            self._contest_push_running = False
            return

        self.hour_contest, self.minute_contest = map(
            int,
            self.contest_push_time.split(":"),
        )

    def _get_next_run_contest(self) -> datetime.datetime:
        """计算下次比赛的推送时间"""
        now = datetime.datetime.now()
        target = now.replace(
            hour=self.hour_contest,
            minute=self.minute_contest,
            second=0,
            microsecond=0,
        )

        if target <= now:
            target += datetime.timedelta(days=1)

        return target

    def _get_next_run_submission(self) -> datetime.datetime:
        """计算下次提交轮询时间"""
        loop_seconds = max(1, int(self.loop_time))
        return datetime.datetime.now() + datetime.timedelta(seconds=loop_seconds)

    @staticmethod
    def _format_run_time(run_time: datetime.datetime) -> str:
        return run_time.strftime("%Y-%m-%d %H:%M:%S")

    def _log_next_contest_run(self, run_time: datetime.datetime | None = None) -> None:
        run_time = run_time or self._get_next_run_contest()
        logger.info(f"下次比赛推送时间：{self._format_run_time(run_time)}")

    def _log_next_submission_run(self, run_time: datetime.datetime | None = None) -> None:
        run_time = run_time or self._get_next_run_submission()
        logger.info(f"下次提交查询时间：{self._format_run_time(run_time)}")

    async def _wait_for_api_request_slot(self) -> None:
        """统一限制自动任务的 Codeforces API 请求起点"""
        async with self._api_request_lock:
            now = time.monotonic()
            if self._last_api_request_time is not None:
                elapsed = now - self._last_api_request_time
                wait_seconds = self.API_REQUEST_INTERVAL_SECONDS - elapsed
                if wait_seconds > 0:
                    # 锁内等待可以保证后续任务按进入顺序排队，不会同时醒来抢请求位
                    await asyncio.sleep(wait_seconds)

            self._last_api_request_time = time.monotonic()

    async def _contest_push_to_sessions(self) -> None:
        """自动推送比赛信息到指定群聊"""
        # 比赛查询也是 Codeforces API 请求，必须和提交轮询共享节流
        await self._wait_for_api_request_slot()
        result = await self.contest_info_handler.ContestInfoRequest(self.contest_number)
        message = self.build_contest_message(result)

        for recv in self.contest_push_sessions:
            logger.info(f"准备向群聊 {recv} 推送比赛信息")
            if self.contest_message_sender is not None:
                await self.contest_message_sender(recv, result, message)
            else:
                await self.message_sender(recv, message)
            logger.info(f"已经向群聊 {recv} 发送最近 {self.contest_number} 条比赛信息")

    async def _auto_time_scheduler_contest(self) -> None:
        """自动化任务：按照规定时间向指定群聊推送比赛信息"""
        while self._contest_push_running:
            try:
                next_run = self._get_next_run_contest()
                wait_seconds = (next_run - datetime.datetime.now()).total_seconds()

                if wait_seconds > 0:
                    # 这里睡到下一次固定时刻；取消任务时 asyncio.sleep 会立刻响应
                    await asyncio.sleep(wait_seconds)

                if self._contest_push_running:
                    logger.info("开始向指定群聊推送比赛任务")
                    await self._contest_push_to_sessions()
                    logger.info("比赛任务推送完成")
                    self._log_next_contest_run()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"比赛任务推送出错：{e}")
                self._log_next_contest_run()
                # 失败后短暂重试，避免一次网络抖动导致后台任务永久停止
                await asyncio.sleep(self.CONTEST_RETRY_SECONDS)

    async def _auto_time_scheduler_submission(self) -> None:
        """自动化任务：定时轮询用户提交记录"""
        while self._submission_push_running:
            try:
                if self._submission_push_running:
                    await self._poll_submission_once()

                next_run = self._get_next_run_submission()
                wait_seconds = (next_run - datetime.datetime.now()).total_seconds()
                if self._submission_push_running and wait_seconds > 0:
                    self._log_next_submission_run(next_run)
                    await asyncio.sleep(wait_seconds)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"提交查询出错: {e}")
                retry_seconds = max(1, int(self.loop_time))
                next_run = datetime.datetime.now() + datetime.timedelta(
                    seconds=retry_seconds
                )
                self._log_next_submission_run(next_run)
                # 提交轮询失败后按原轮询间隔重试，避免异常把后台任务杀死
                await asyncio.sleep(retry_seconds)

    async def _poll_submission_once(self) -> None:
        """执行一次提交轮询"""
        if not self.enable_getter():
            logger.info("插件功能被阻止，跳过本轮提交信息查询")
            return

        logger.info("开始执行提交信息查询")
        bindings = await self.user_db_handler.alist_bindings(
            only_broadcast_enabled=True
        )

        # 同一个 cf_handle 可能绑定在多个群，API 只查一次，再分发到各群绑定
        handle_map = {}
        for binding in bindings:
            handle_map.setdefault(binding.cf_handle.casefold(), []).append(binding)

        # 每个 handle 查询前都会进入 API 节流器，防止绑定数量多时请求过密
        for handle_bindings in handle_map.values():
            cf_handle = handle_bindings[0].cf_handle
            logger.info(f"查询 handle: {cf_handle}")
            await self._poll_handle_submissions(cf_handle, handle_bindings)

    async def _poll_handle_submissions(self, cf_handle: str, handle_bindings: list) -> None:
        """查询并处理单个 Codeforces handle 的最新提交"""
        try:
            await self._wait_for_api_request_slot()
            result = await self.user_status_handler.UserStatusRequest(cf_handle)
        except Exception as e:
            logger.error(f"查询 {cf_handle} 提交记录出错: {e}")
            return

        if not result.ok:
            logger.warning(f"查询 {cf_handle} 提交记录失败: {result.message}")
            return

        status = result.latest_status
        if status is None:
            logger.info(f"{cf_handle} 暂无提交记录")
            return

        fingerprint = self._build_submission_fingerprint(status)

        if status.verdict != "OK":
            # 首次看到非 AC 提交时也写入基线，避免下一次 AC 被误判为历史提交
            await self._initialize_non_ac_baseline(handle_bindings, fingerprint)
            logger.info(f"{cf_handle} 最新提交不是 AC，跳过")
            return

        for binding in handle_bindings:
            # 指纹相同说明已经播报过，直接跳过
            if binding.last_ac_fingerprint == fingerprint:
                continue

            if binding.last_ac_fingerprint is None:
                # 首次看到 AC 只建立基线，避免插件重启后播报旧提交
                await self.user_db_handler.aupdate_last_ac_fingerprint(
                    binding.user_id,
                    binding.group_id,
                    fingerprint,
                )
                logger.info(
                    f"为 {binding.cf_handle} 在群 {binding.group_id} 初始化 AC 指纹"
                )
                continue

            message = self._build_submission_message(binding, status)
            # 真正的发送仍交给 main.py 注入的 message_sender
            try:
                await self.message_sender(
                    binding.group_id,
                    message,
                )
            except Exception as e:
                logger.error(
                    f"向群聊 {binding.group_id} 播报 {binding.cf_handle} 的新 AC 失败: {e}"
                )
                continue
            await self.user_db_handler.aupdate_last_ac_fingerprint(
                binding.user_id,
                binding.group_id,
                fingerprint,
            )
            logger.info(
                f"已经向群聊 {binding.group_id} 播报 {binding.cf_handle} 的新 AC"
            )

    async def _initialize_non_ac_baseline(self, handle_bindings: list, fingerprint: str) -> None:
        """首次轮询到非 AC 提交时写入基线，避免之后第一条 AC 被误判为历史记录"""
        for binding in handle_bindings:
            if binding.last_ac_fingerprint is None:
                await self.user_db_handler.aupdate_last_ac_fingerprint(
                    binding.user_id,
                    binding.group_id,
                    f"baseline:{fingerprint}",
                )

    @staticmethod
    def _build_submission_fingerprint(status) -> str:
        """构造提交记录指纹，优先使用 Codeforces 全局唯一 submission id"""
        return str(status.id)

    @staticmethod
    def _build_submission_message(binding, status) -> str:
        """构造 AC 播报消息。"""
        problem = status.problem
        problem_id = (
            f"{problem.contestId}{problem.index}"
            if problem.contestId is not None
            else problem.index
        )
        problem_url = (
            f"https://codeforces.com/contest/{problem.contestId}/problem/{problem.index}"
            if problem.contestId is not None
            else "https://codeforces.com/problemset"
        )
        submit_time = datetime.datetime.fromtimestamp(
            status.creationTimeSeconds
        ).strftime("%Y-%m-%d %H:%M:%S")
        rating_text = f"{problem.rating}" if problem.rating is not None else "未知"

        return "\n".join(
            [
                "检测到新的 AC 提交！",
                f"用户: {binding.cf_handle} (QQ: {binding.user_id})",
                f"题目: {problem_id}. {problem.name}",
                f"难度: {rating_text}",
                f"语言: {status.programmingLanguage}",
                f"提交时间: {submit_time}",
                f"题目链接: {problem_url}",
            ]
        )

    @staticmethod
    def build_contest_message(result) -> str:
        """封装比赛消息格式化逻辑"""
        if not result.ok or result.contests is None:
            return result.message

        contest_messages = []

        for index, contest in enumerate(result.contests, start=1):
            if contest.start_time_seconds is None:
                start_time = "未知"
            else:
                start_time = datetime.datetime.fromtimestamp(
                    contest.start_time_seconds
                ).strftime("%Y-%m-%d %H:%M:%S")

            duration_hours = contest.duration_seconds // 3600
            duration_minutes = contest.duration_seconds % 3600 // 60
            duration = f"{duration_hours} 小时 {duration_minutes} 分钟"

            contest_messages.append(
                "\n".join(
                    [
                        f"{index}. {contest.name}",
                        f"比赛 ID: {contest.id}",
                        f"比赛类型: {contest.type}",
                        f"当前状态: {contest.phase}",
                        f"开始时间: {start_time}",
                        f"持续时间: {duration}",
                        f"比赛链接: https://codeforces.com/contest/{contest.id}",
                    ]
                )
            )

        return "\n\n".join(contest_messages)

    @staticmethod
    def _validate_time(time_str: str) -> bool:
        """验证 HH:MM 时间格式是否合法"""
        if not isinstance(time_str, str):
            return False

        if re.fullmatch(r"\d{2}:\d{2}", time_str) is None:
            return False

        hour, minute = map(int, time_str.split(":"))
        return 0 <= hour <= 23 and 0 <= minute <= 59
