# main.py
from pathlib import Path
import sqlite3
import time
import asyncio
import datetime
import re

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig, logger
from astrbot.api.message_components import At, Plain, BaseMessageComponent
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .user_handle.user_info import UserInfoHandler
from .user_status.user_status import UserStatusHandler
from .contests.contest_info import ContestInfoHandler
from .storage.user_db import DataStorageHandler


PLUGIN_NAME = "astrbot_plugin_for_XCPC"


@register(
    PLUGIN_NAME,
    "Bricks0411",
    "基于 Astrbot 框架的简单插件，为算法竞赛选手提供各种功能",
    "0.0.1",
)
class PluginForXCPC(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        # 配置项实例化
        self.config = config

        # 配置参数实例化
        self.loop_time = config["loop_time"]
        
        self.admin_id = config["admin_setting"]["Admin ID"]
        self.api_key = config["admin_setting"]["API key"]
        self.enable = config["admin_setting"]["enable"]

        self.contest_number = config["contest_setting"]["contest_number"]
        self.contest_push_time = config["contest_setting"]["contest_push_time"]
        self.contest_push_sessions = config["contest_setting"]["contest_push_sessions"]

        # 模块类实例化
        self.user_info_handler = UserInfoHandler()
        self.user_status_handler = UserStatusHandler()
        self.contest_info_handler = ContestInfoHandler()
        self.user_db_handler = DataStorageHandler(db_path=self._build_user_db_path())
        self.hour_contest = 0
        self.minute_contest = 0

        self._contest_push_running = True
        if not self.contest_push_time:
            logger.info("未设置比赛推送时间，跳过")
            self._contest_push_running = False
        elif not self._validate_time(self.contest_push_time):
            logger.warn("时间格式错误，跳过配置")
            self._contest_push_running = False
        else:
            self.hour_contest, self.minute_contest = map(int, self.contest_push_time.split(':'))
        
        self._contest_scheduler_task: asyncio.Task | None = None

    def _build_user_db_path(self) -> Path:
        plugin_data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        return plugin_data_dir / "user_bindings.sqlite3"

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        if self._contest_push_running and self.contest_push_sessions:
            self._contest_scheduler_task = asyncio.create_task(
                self._auto_time_scheduler_contest()
            )

    def GetArgs(self, messages: list[BaseMessageComponent]):
        """参数解析逻辑"""
        args = []
        for msg in messages:
            if isinstance(msg, At):
                continue
            if isinstance(msg, Plain):
                text = msg.text.strip()
                if text:
                    args.extend(text.split())
        return args
    
    def build_contest_message(self, result):
        """封装消息格式化逻辑"""
        if not result.ok or result.contests is None:
            return result.message
        
        contest_messages = []

        for index, contest in enumerate(result.contests, start=1):
            if contest.start_time_seconds is None:
                start_time = "未知"
            else:
                start_time = datetime.datetime.fromtimestamp(contest.start_time_seconds).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

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

        message_chain = "\n\n".join(contest_messages)

        return message_chain

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
    
    # 静态方法区
    @staticmethod
    def _validate_time(time_str: str):
        """验证时间是否合法"""
        if not isinstance(time_str, str):
            return False

        if re.fullmatch(r"\d{2}:\d{2}", time_str) is None:
            return False

        hour, minute = map(int, time_str.split(':'))
        return 0 <= hour <= 23 and 0 <= minute <= 59
        
    
    # 异步任务区
    async def _contest_push_sessions(self):
        """自动推送比赛信息到指定群聊"""
        result_message = await self.contest_info_handler.ContestInfoRequest(self.contest_number)
        msg = MessageChain().message(result_message)

        for recv in self._contest_push_sessions:
            await self.context.send_message(recv, msg)
            logger.info(f"已经向群聊 {recv} 发送最近 {self.contest_number} 条消息")


    # 自动化任务区
    async def _auto_time_scheduler_contest(self):
        """自动化任务：按照规定时间向指定群聊推送比赛信息"""
        while self._contest_push_running:
            try:
                next_run = self._get_next_run_contest()
                wait_seconds = (next_run - datetime.datetime.now()).total_seconds()

                if wait_seconds > 0:
                    logger.info(f"下次执行时间：{next_run.strftime('%Y-%m-%d %H:%M:%S')}")
                    await asyncio.sleep(wait_seconds)

                if self._contest_push_running:
                    logger.info(f"开始向指定群聊推送比赛任务")
                    await self._contest_push_sessions()
                    logger.info(f"比赛任务推送完成")
            except Exception as e:
                logger.error(f"比赛任务推送出错：{e}")
                break


    # 用户 / 管理员指令区
    @filter.command("cf", alias={"CF", "cF", "Cf"})
    async def GetCodeforcesUserInfo(self, event: AstrMessageEvent):
        """查询指定 Codeforces 用户信息"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /cf 指令")
            return

        messages = event.get_messages()
        args = self.GetArgs(messages)

        if len(args) != 2:
            logger.warning(f"参数数量不合法，期望 2，接收到 {len(args)}")
            yield event.plain_result("用法: /cf <Codeforces handle>")
            return

        user_handle = args[1]
        logger.info(f"从消息链中解析出 codeforces handle: {user_handle}")

        result = await self.user_info_handler.UserInfoRequest(user_handle)
        logger.warning(result.message)
        yield event.plain_result(result.message)


    @filter.command("比赛", alias={"contest", "contests", "cf比赛"})
    async def GetCodeForcesContestInfo(self, event: AstrMessageEvent):
        """查询 Codeforces 比赛信息"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /比赛 指令")
            return
        
        logger.info(f"向 Codeforces.com 请求最近 {self.contest_number} 场的比赛数据")
        result = await self.contest_info_handler.ContestInfoRequest(self.contest_number)
        logger.info(result.message)

        message_chain = self.build_contest_message(result)

        yield event.plain_result(result.message)
        yield event.plain_result(message_chain)


    @filter.command("绑定", alias={"绑定cf"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def BindUserCodeForcesSubmitInfo(self, event: AstrMessageEvent):
        """用户绑定 Codeforces 用户信息"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /绑定 指令")
            return

        # 用户信息获取
        user_id = event.get_sender_id()
        group_id = event.get_group_id()
        messages = event.get_messages()
        args = self.GetArgs(messages)
        
        if len(args) != 2:
            logger.warning(f"参数数量不合法，期望 2，接收到 {len(args)}")
            yield event.plain_result("用法：/绑定 <Codeforces handle>")
            return

        cf_handle = args[1]
        logger.info(f"用户 {user_id} 尝试在群聊 {group_id} 绑定 cf 用户 {cf_handle}")

        # 判断用户输入的 cf handle 是否有效
        handle_result = await self.user_info_handler.UserInfoRequest(cf_handle)
        if handle_result.ok is False:
            logger.warning(f"请求出错！原因：{handle_result.message}")
            yield event.plain_result(f"请求出错！原因：{handle_result.message}")
            return
        
        # 判断该 cf handle 是否被其他用户绑定
        existing = await self.user_db_handler.aget_group_binding_by_handle(group_id, cf_handle)
        if existing is not None and existing.user_id != str(user_id):
            logger.info(f"检测到 {existing.cf_handle} 已经被 {existing.user_id} 绑定")
            yield event.plain_result("该 Codeforces 用户已被本群其他用户绑定")
            return

        # 调用数据库类方法，修改用户绑定信息
        try:
            await self.user_db_handler.abind_user(user_id, group_id, cf_handle, None)
        except sqlite3.IntegrityError:
            logger.info(f"检测到 {cf_handle} 已经被 {user_id} 绑定")
            yield event.plain_result("该 Codeforces 用户已被本群其他用户绑定")
            return

        logger.info(f"用户 {user_id} 绑定 cf handle {cf_handle} 成功！")
        yield event.plain_result("绑定成功！")

    
    @filter.command("解绑")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def UnBindUserCodeForcesSubmitInfo(self, event: AstrMessageEvent):
        """解绑逻辑"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /解绑 指令")
            return
        
        # 用户信息获取
        user_id = event.get_sender_id()
        group_id = event.get_group_id()

        result = await self.user_db_handler.aunbind_user(user_id, group_id)
        if not result:
            yield event.plain_result("没有绑定记录")
            return

        logger.info(f"用户 {user_id} 解绑成功")
        yield event.plain_result(f"解绑成功！(user_id: {user_id})")


    @filter.command("查询绑定")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def CheckUserBindInformation(self, event: AstrMessageEvent):
        """查询绑定信息，仅支持查询发送者自身信息"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /查询绑定 指令")
            return
        
        # 用户信息获取
        user_id = event.get_sender_id()
        group_id = event.get_group_id()
        
        # 获取用户绑定信息
        result = await self.user_db_handler.aget_binding(user_id, group_id)

        if result is None:
            logger.info(f"用户 {user_id} 未在群 {group_id} 中绑定任何信息")
            yield event.plain_result(f"您还暂未绑定用户！(user_id: {user_id})")
            return
        
        logger.info(f"用户 {user_id} 在群 {group_id} 中绑定的 cf 用户为 {result.cf_handle}")
        yield event.plain_result(f"您当前绑定的用户为 {result.cf_handle} (user_id: {user_id})")

    
    @filter.command("显示记录")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def EnableUserBroadCast(self, event: AstrMessageEvent):
        """修改过题记录可见性为 true"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /显示记录 指令")
            return
        
        # 用户信息获取
        user_id = event.get_sender_id()
        group_id = event.get_group_id()

        # 调用数据库类方法，修改用户过题记录可见性
        result = await self.user_db_handler.aset_broadcast_enabled(user_id, group_id, True)

        if result is None:
            logger.info(f"用户 {user_id} 不在群 {group_id} 的绑定记录中，无法开启过题记录播报")
            yield event.plain_result("您还暂未绑定用户，请先使用 /绑定 <Codeforces handle>")
            return
        
        logger.info(f"用户 {user_id} 在群 {group_id} 中开启过题记录播报成功")
        yield event.plain_result("已开启过题记录播报")

    
    @filter.command("隐藏记录")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def DisableUserBroadCast(self, event: AstrMessageEvent):
        """修改过题记录可见性为 False"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /隐藏记录 指令")
            return
        
        # 用户信息获取
        user_id = event.get_sender_id()
        group_id = event.get_group_id()

        # 调用数据库类方法，修改用户过题记录可见性
        result = await self.user_db_handler.aset_broadcast_enabled(user_id, group_id, False)

        if result is None:
            logger.info(f"用户 {user_id} 不在群 {group_id} 的绑定记录中，无法关闭过题记录播报")
            yield event.plain_result("您还暂未绑定用户，请先使用 /绑定 <Codeforces handle>")
            return
        
        logger.info(f"用户 {user_id} 在群 {group_id} 中关闭过题记录播报成功")
        yield event.plain_result("已关闭过题记录播报")


    # 管理员指令区
    @filter.command("enable_cf")
    async def EnablePlugin(self, event: AstrMessageEvent):
        """启用插件功能，仅配置的管理员 ID 可调用"""
        user_id = event.get_sender_id()
        logger.info(f"用户 {user_id} 尝试启用插件总开关")
        if user_id not in self.admin_id:
            logger.warning(f"用户 {user_id} 无权执行该操作，退出")
            return
        if self.enable is True:
            yield event.plain_result("[astrbot_plugin_for_XCPC] 使能开关已经开启！无需重复操作")
            logger.info("检测到重复操作")
            return
        self.enable = True
        yield event.plain_result("[astrbot_plugin_for_XCPC] 使能开关已开启！bot 将重新开始响应指令")
        logger.info("插件总开关已经开启")

    @filter.command("disable_cf")
    async def DisablePlugin(self, event: AstrMessageEvent):
        """关闭插件功能，仅配置的管理员 ID 可调用"""
        user_id = event.get_sender_id()
        logger.info(f"用户 {user_id} 尝试关闭插件总开关")
        if user_id not in self.admin_id:
            logger.warning(f"用户 {user_id} 无权执行该操作，退出")
            return
        if self.enable is False:
            yield event.plain_result("[astrbot_plugin_for_XCPC] 使能开关已经关闭！无需重复操作")
            logger.info("检测到重复操作")
            return
        self.enable = False
        yield event.plain_result("[astrbot_plugin_for_XCPC] 使能开关已关闭！之后不会响应任何指令，直到开关被重新开启")
        logger.info("插件总开关已经关闭")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        self._contest_push_running = False
        if self._contest_scheduler_task:
            self._contest_scheduler_task.cancel()
        await self.user_db_handler.aclose()
        
