# main.py
from datetime import datetime
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig, logger
from astrbot.api.message_components import At, Plain, BaseMessageComponent
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .user_handle.user_info import UserInfoHandler
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
        self.loop_time = config["loop_time"]
        
        self.admin_id = config["admin_setting"]["Admin ID"]
        self.api_key = config["admin_setting"]["API key"]
        self.enable = config["admin_setting"]["enable"]

        self.contest_number = config["contest_setting"]["contest_number"]

        # 模块类实例化
        self.user_info_handler = UserInfoHandler()
        self.contest_info_handler = ContestInfoHandler()
        self.user_db_handler = DataStorageHandler(db_path=self._build_user_db_path())

    def _build_user_db_path(self) -> Path:
        plugin_data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        return plugin_data_dir / "user_bindings.sqlite3"

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""

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
                start_time = datetime.fromtimestamp(contest.start_time_seconds).strftime(
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
            logger.warning(f"参数数量不合法，期望 1，接收到 {len(args)}")
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

        user_id = event.get_sender_id()
        group_id = event.get_group_id()
        messages = event.get_messages()
        args = self.GetArgs(messages)
        
        if len(args) != 2:
            logger.warning(f"参数数量不合法，期望 1，接收到 {len(args)}")
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

        # 调用数据库类方法，修改用户绑定信息
        await self.user_db_handler.abind_user(user_id, group_id, cf_handle, None)
        logger.info(f"用户 {user_id} 绑定 cf handle {cf_handle} 成功！")
        yield event.plain_result("绑定成功！")


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
        await self.user_db_handler.aclose()
