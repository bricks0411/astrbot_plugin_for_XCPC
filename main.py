# main.py
"""
AstrBot 插件入口模块。

本文件负责把各个业务模块接入 AstrBot：
- 用户资料查询命令调用 user_handle。
- 比赛查询和比赛卡片渲染调用 contests。
- 用户绑定、播报开关和指纹记录调用 storage。
- 自动比赛推送和 AC 播报调用 automation。

入口层尽量只做参数解析、权限判断、消息发送和异常回退。
真实的 HTTP 请求、数据库操作和卡片数据构造都下沉到独立模块，避免命令函数过重。

维护要点：
- initialize 负责启动后台任务，terminate 负责按相反方向释放资源。
- 命令函数是 AstrBot 的交互边界，所有用户输入都要在这里校验。
- /cf 和 /比赛 优先渲染图片，渲染失败时回退为纯文本。
- 绑定类命令只允许群聊使用，因为绑定关系包含会话维度。
- 管理员命令只改变内存中的 enable 开关，不改写配置文件。
- 自动推送模块通过 enable_getter 读取 enable，能即时响应开关变化。
- html_render 可能返回非图片路径，因此发送前必须验证文件头。
- t2i 临时文件清理只删除 AstrBot 临时目录下的目标文件名模式。
- 任何涉及会话 ID 的逻辑都应使用 unified_msg_origin。
- 发送自动消息时不依赖原始事件对象，只使用 session_id。
- 数据库路径固定在插件数据目录，避免污染插件代码目录。
- 用户可见错误尽量简短，详细原因保留在日志中。
- Codeforces API 查询失败不应让命令抛出未捕获异常。
- 卡片渲染失败不影响核心查询结果，只影响展示形式。
- 指纹测试命令会暴露内部去重状态，因此只开放给管理员。
- 新增命令时优先复用 GetArgs 解析文本参数。
- 新增图片渲染能力时要复用 _is_rendered_image_file 校验。
- 关闭插件时先停止后台任务，再关闭数据库连接。
- 命令函数中不要直接操作 SQLite，同步/异步封装都在 storage 模块。
- 入口层不保存 Codeforces 原始 JSON，只传递内部结果模型。
- 修改配置字段名时需要同步 _conf_schema.json 和这里的读取路径。
- 自动推送和手动查询共享同一套比赛卡片渲染器。
- 自动推送文本回调用于提交播报和比赛卡片失败兜底。
- 日志信息用于排查远端 API、渲染服务和数据库状态。
- 这里的注释以流程边界为主，避免重复解释下层模块内部实现。
- 用户命令通常使用 yield 返回 AstrBot 结果，后台回调直接调用 context 发送。
- 群聊命令读取 session_id，不直接假设 group_id 是纯数字群号。
- 绑定前先查 Codeforces 用户是否存在，避免无效 handle 进入数据库。
- 数据库仍保留唯一约束，用于兜底并发场景下的重复绑定。
- enable 开关只阻止命令和自动轮询，不销毁已经创建的后台任务。
- 比赛自动推送的图片失败时，仍会发送 build_contest_message 文本。
- 用户资料卡片失败时，仍会发送 user.info 返回的 message。
- terminate 中忽略清理任务的 CancelledError，属于正常关闭流程。
- 不同命令的参数数量校验尽量在远端 API 请求前完成。
- 这里不做 Codeforces API 节流，自动任务节流在 automation 模块中实现。
"""
import asyncio
from pathlib import Path
import sqlite3
import time

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig, logger
from astrbot.api.message_components import At, Plain, BaseMessageComponent
from astrbot.core.utils.astrbot_path import get_astrbot_data_path, get_astrbot_temp_path

from .user_handle.user_info import UserInfoHandler
from .user_handle.user_card import UserProfileCardRenderer
from .user_status.user_status import UserStatusHandler
from .contests.contest_info import ContestInfoHandler
from .contests.contest_card import ContestCardRenderer
from .storage.user_db import DataStorageHandler
from .automation import AutomationPushHandler


PLUGIN_NAME = "astrbot_plugin_for_XCPC"
T2I_TEMP_FILE_PATTERN = "io_temp_img_*"
T2I_TEMP_FILE_TTL_SECONDS = 24 * 60 * 60
T2I_CLEANUP_INTERVAL_SECONDS = 60 * 60


@register(
    PLUGIN_NAME,
    "Bricks0411",
    "基于 Astrbot 框架的简单插件，为算法竞赛选手提供各种功能",
    "0.0.1",
)
class PluginForXCPC(Star):
    """XCPC 辅助插件主类，负责 AstrBot 生命周期和命令注册。"""

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
        # t2i 临时文件清理任务在 initialize 中启动，terminate 中取消。
        self._t2i_cleanup_task: asyncio.Task | None = None

        # 模块类实例化
        self.user_info_handler = UserInfoHandler()
        self.user_card_renderer = UserProfileCardRenderer()
        self.user_status_handler = UserStatusHandler()
        self.contest_info_handler = ContestInfoHandler()
        self.contest_card_renderer = ContestCardRenderer()
        self.user_db_handler = DataStorageHandler(db_path=self._build_user_db_path())
        # 自动化模块通过回调发送消息，避免直接依赖 AstrBot 事件对象。
        self.automation_push_handler = AutomationPushHandler(
            user_status_handler=self.user_status_handler,
            contest_info_handler=self.contest_info_handler,
            user_db_handler=self.user_db_handler,
            loop_time=self.loop_time,
            enable_getter=lambda: self.enable,
            message_sender=self._send_automation_message,
            contest_message_sender=self._send_contest_automation_message,
            contest_number=self.contest_number,
            contest_push_time=self.contest_push_time,
            contest_push_sessions=self.contest_push_sessions,
        )

    def _build_user_db_path(self) -> Path:
        """构造插件专用 SQLite 数据库路径。"""
        plugin_data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        return plugin_data_dir / "user_bindings.sqlite3"

    def _get_event_session_id(self, event: AstrMessageEvent) -> str:
        """从 AstrBot 事件中提取统一会话 ID。"""
        session_id = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if not session_id:
            raise ValueError("无法获取当前会话 ID")
        return session_id

    @staticmethod
    def _is_rendered_image_file(file_path: str | Path) -> bool:
        """用文件头判断 html_render 返回值是否是真实图片文件。"""
        try:
            with Path(file_path).open("rb") as image_file:
                header = image_file.read(12)
        except OSError:
            return False

        return (
            header.startswith(b"\x89PNG\r\n\x1a\n")
            or header.startswith(b"\xff\xd8\xff")
            or header.startswith(b"GIF87a")
            or header.startswith(b"GIF89a")
            or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
        )

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        # 启动前先清理一次历史 t2i 文件，再创建长期清理任务。
        await self._cleanup_t2i_temp_files()
        self._t2i_cleanup_task = asyncio.create_task(self._t2i_cleanup_loop())
        await self.automation_push_handler.start()

    async def _t2i_cleanup_loop(self) -> None:
        """周期性清理 AstrBot 文转图临时文件。"""
        while True:
            try:
                await asyncio.sleep(T2I_CLEANUP_INTERVAL_SECONDS)
                await self._cleanup_t2i_temp_files()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"定时清理 t2i 临时文件失败: {e}")

    async def _cleanup_t2i_temp_files(self) -> None:
        """删除超过 TTL 的 t2i 临时图片。"""
        temp_dir = Path(get_astrbot_temp_path()).resolve()
        if not temp_dir.exists():
            return

        now = time.time()
        deleted_count = 0
        deleted_size = 0
        expired_before = now - T2I_TEMP_FILE_TTL_SECONDS

        for file_path in temp_dir.glob(T2I_TEMP_FILE_PATTERN):
            try:
                resolved_path = file_path.resolve()
                # 只删除 temp_dir 直属文件，避免通配符或符号链接误伤其它路径。
                if resolved_path.parent != temp_dir or not resolved_path.is_file():
                    continue

                stat = resolved_path.stat()
                if stat.st_mtime > expired_before:
                    continue

                deleted_size += stat.st_size
                resolved_path.unlink()
                deleted_count += 1
            except OSError as e:
                logger.warning(f"清理 t2i 临时文件失败: {file_path}, {e}")

        if deleted_count:
            logger.info(f"已清理 {deleted_count} 个 t2i 临时文件，释放 {deleted_size} 字节")

    async def _send_automation_message(self, session_id: str, message: str) -> None:
        """
        回调：发送自动化模块生成的纯文本消息。
        """
        logger.info("执行自动信息回调")
        await self.context.send_message(session_id, MessageChain().message(message))

    async def _render_contest_card_image(self, result) -> Path:
        """渲染比赛卡片，并校验 AstrBot 返回的是图片文件。"""
        template, data, options = self.contest_card_renderer.build(result)
        card_path = await self.html_render(template, data, return_url=False, options=options)
        if not self._is_rendered_image_file(card_path):
            raise ValueError(
                f"AstrBot HTML 渲染返回的文件不是图片: {card_path}，"
                "请检查 AstrBot 文转图服务状态"
            )
        return Path(card_path)

    async def _send_contest_automation_message(
        self,
        session_id: str,
        result,
        fallback_message: str,
    ) -> None:
        """比赛信息卡片发送逻辑"""
        try:
            card_path = await self._render_contest_card_image(result)
            await self.context.send_message(
                session_id,
                MessageChain().file_image(str(card_path)),
            )
        except Exception as e:
            logger.error(f"渲染比赛信息卡片失败，回退为文本推送: {e}")
            await self._send_automation_message(session_id, fallback_message)

    def GetArgs(self, messages: list[BaseMessageComponent]):
        """参数解析逻辑"""
        args = []
        for msg in messages:
            # @ 消息不参与命令参数解析，只解析纯文本片段。
            if isinstance(msg, At):
                continue
            if isinstance(msg, Plain):
                text = msg.text.strip()
                if text:
                    args.extend(text.split())
        return args
    
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
        if not result.ok or result.profile is None:
            # API 失败直接把错误文本回给用户，不进入卡片渲染流程。
            logger.warning(result.message)
            yield event.plain_result(result.message)
            return

        try:
            template, data, options = self.user_card_renderer.build(result.profile)
            card_path = await self.html_render(template, data, return_url=False, options=options)
            # html_render 异常时可能返回非图片路径，发送前必须做文件头校验。
            if not self._is_rendered_image_file(card_path):
                raise ValueError(
                    f"AstrBot HTML 渲染返回的文件不是图片: {card_path}，"
                    "请检查 AstrBot 文转图服务状态"
                )
            logger.info(f"已渲染 Codeforces 用户信息卡片: {card_path}")
            yield event.image_result(str(card_path))
        except Exception as e:
            logger.error(f"渲染 Codeforces 用户信息卡片失败: {e}")
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

        # 文本消息同时作为渲染失败时的兜底内容。
        message_chain = self.automation_push_handler.build_contest_message(result)

        if not result.ok or result.contests is None:
            yield event.plain_result(result.message)
            return

        try:
            card_path = await self._render_contest_card_image(result)
            logger.info(f"已渲染 Codeforces 比赛信息卡片: {card_path}")
            yield event.image_result(str(card_path))
        except Exception as e:
            logger.error(f"渲染 Codeforces 比赛信息卡片失败: {e}")
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
        group_id = self._get_event_session_id(event)
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
            # 数据库唯一约束是最后一道防线，避免并发绑定同一 handle。
            await self.user_db_handler.abind_user(user_id, group_id, cf_handle, None)
        except sqlite3.IntegrityError:
            logger.info(f"检测到 {cf_handle} 已经被 {user_id} 绑定")
            yield event.plain_result("该 Codeforces 用户已被本群其他用户绑定")
            return

        logger.info(f"用户 {user_id} 绑定 cf handle {cf_handle} 成功！")
        yield event.plain_result(f"绑定成功！(user_id: {user_id}, cf_handle: {cf_handle})")

    
    @filter.command("解绑")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def UnBindUserCodeForcesSubmitInfo(self, event: AstrMessageEvent):
        """解绑逻辑"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /解绑 指令")
            return
        
        # 用户信息获取
        user_id = event.get_sender_id()
        group_id = self._get_event_session_id(event)

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
        group_id = self._get_event_session_id(event)
        
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
        group_id = self._get_event_session_id(event)

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
        group_id = self._get_event_session_id(event)

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
            # 管理员命令不回显具体原因，减少普通用户误触时的噪声。
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
            # 管理员命令不回显具体原因，减少普通用户误触时的噪声。
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
        if self._t2i_cleanup_task:
            # 先停清理任务，再停自动推送和数据库连接，避免后台任务继续访问已关闭资源。
            self._t2i_cleanup_task.cancel()
            try:
                await self._t2i_cleanup_task
            except asyncio.CancelledError:
                pass
        await self.automation_push_handler.stop()
        await self.user_db_handler.aclose()
        

    @filter.command("测试指纹", alias={"fingerprint", "test_fingerprint"})
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def CheckCurrentUserSubmissionFingerprint(self, event: AstrMessageEvent):
        """测试命令：查询当前用户最新提交记录的指纹"""
        if self.enable is False:
            logger.warning("插件功能被阻止，无法使用 /测试指纹 指令")
            return
        
        user_id = event.get_sender_id()
        if user_id not in self.admin_id:
            # 指纹测试命令会暴露内部状态，只允许管理员使用。
            logger.warning(f"用户 {user_id} 无权执行该操作，退出")
            return

        user_id = event.get_sender_id()
        group_id = self._get_event_session_id(event)

        binding = await self.user_db_handler.aget_binding(user_id, group_id)
        if binding is None:
            logger.info(f"用户 {user_id} 未在群 {group_id} 中绑定任何信息，无法查询提交指纹")
            yield event.plain_result("您还暂未绑定用户，请先使用 /绑定 <Codeforces handle>")
            return

        result = await self.user_status_handler.UserStatusRequest(binding.cf_handle)
        if not result.ok:
            logger.warning(f"查询 {binding.cf_handle} 提交指纹失败: {result.message}")
            yield event.plain_result(f"查询提交指纹失败：{result.message}")
            return

        status = result.latest_status
        if status is None:
            logger.info(f"{binding.cf_handle} 暂无提交记录，无法生成提交指纹")
            yield event.plain_result(f"{binding.cf_handle} 暂无提交记录，无法生成提交指纹")
            return

        fingerprint = self.automation_push_handler._build_submission_fingerprint(status)
        # 该命令用于排查自动播报去重问题，因此直接展示当前指纹和已记录指纹。
        logger.info(
            f"用户 {user_id} 在群 {group_id} 查询 {binding.cf_handle} 最新提交指纹: {fingerprint}"
        )

        problem = status.problem
        problem_id = (
            f"{problem.contestId}{problem.index}"
            if problem.contestId is not None
            else problem.index
        )
        verdict_text = status.verdict or "未知"

        yield event.plain_result(
            "\n".join(
                [
                    "当前用户最新提交指纹：",
                    f"Codeforces 用户: {binding.cf_handle}",
                    f"提交指纹: {fingerprint}",
                    f"已记录指纹: {binding.last_ac_fingerprint or '无'}",
                    f"提交 ID: {status.id}",
                    f"题目: {problem_id}. {problem.name}",
                    f"判题结果: {verdict_text}",
                ]
            )
        )
