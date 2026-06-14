# user_handle/user_card.py
"""
Codeforces 用户资料卡片渲染模块。

该模块把 CodeforcesUserProfile 转换为 html_render 可用的模板数据。
卡片尺寸固定为 760x430，适合在聊天窗口中直接展示，不依赖用户端缩放。

模板中的颜色由用户 rank 决定：
- accent 用于边条、头像底色、Rating 数字等强视觉元素。
- tint 用于卡片背景渐变，保持不同等级可区分但不过度花哨。

维护要点：
- OPTIONS.clip 固定输出尺寸，CSS 的 html/body/card 尺寸要与之匹配。
- rank 主题集中在 RANK_THEME，模板中只消费 accent 和 tint。
- avatar 优先使用 titlePhoto，其次 avatar，最后使用 handle 缩写兜底。
- 所有文本字段进入模板前都要经过 _escape。
- handle、rank、指标值都设置省略号，避免长文本溢出卡片。
- metrics 固定四项，保证卡片信息密度稳定。
- contribution 使用带符号格式，更贴近 Codeforces 页面展示。
- lastOnlineTimeSeconds 可能缺失，缺失时展示 unknown。
- 头像 URL 可能是协议相对地址，必须在 _normalize_avatar 中补全。
- 该模块只生成渲染数据，不处理 API 请求和消息发送。
- 修改卡片尺寸时需要同步 OPTIONS.clip、html/body 和 .card。
- 修改指标数量时需要同步 .metrics 网格和 build 中的 metrics 列表。
- 新增 rank 时只需扩展 RANK_THEME，不需要改模板结构。
- 未知 rank 会回退到灰色主题，避免新等级导致渲染失败。
- 内联 GitHub SVG 避免外部静态资源依赖。
- 模板注释只用于维护结构说明，不承载业务逻辑。
- 背景渐变保持浅色，防止深色主题影响文字可读性。
- 字体使用系统字体栈，优先兼容 Windows 和常见中文环境。
- 该卡片用于聊天场景，固定尺寸比响应式布局更稳定。
- 渲染失败由 main.py 兜底为纯文本消息。
"""
from __future__ import annotations

import datetime
import html

from .models import CodeforcesUserProfile


class UserProfileCardRenderer:
    """构造 Codeforces 用户信息卡片的 HTML 模板数据。"""

    OPTIONS = {
        "full_page": False,
        "type": "png",
        "clip": {"x": 0, "y": 0, "width": 760, "height": 430},
        "animations": "disabled",
        "caret": "hide",
        "scale": "css",
        "timeout": 10000,
    }

    TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    /*
     * 用户卡片样式维护地图：
     * 1. html/body 与 OPTIONS.clip 共同决定最终图片尺寸。
     * 2. .card 是唯一主容器，负责圆角、阴影和等级背景。
     * 3. .stripe 使用 rank 强调色，快速传达用户等级。
     * 4. .brand 与 .bars 只负责 Codeforces 风格标识。
     * 5. .avatar 优先展示图片，缺失时展示 handle 缩写。
     * 6. .identity 放 handle 和 rank，长文本必须截断。
     * 7. .rating-block 是主视觉区，突出当前 rating。
     * 8. .metrics 是 2x2 指标网格，保持固定信息密度。
     * 9. .metric 内部标签和值都要截断，避免破坏卡片边界。
     * 10. .watermark 固定右下角，不抢占用户信息区域。
     * 11. 修改卡片尺寸时必须同步 clip、html/body、.card 三处。
     * 12. 修改指标数量时必须同步 metrics 网格布局。
     * 13. rank 配色从 Python 数据注入，CSS 不判断 rank 名称。
     * 14. 头像图片使用 object-fit:cover，保证不同尺寸头像都能填满。
     * 15. 所有固定定位都服务于截图稳定性，不适合改成流式布局。
     * 16. 背景保持浅色，避免彩色等级主题影响文字对比度。
     * 17. 字体栈优先兼容 Windows 中文环境和常见浏览器。
     * 18. SVG 水印内联在模板中，避免外链资源加载失败。
     * 19. 不要移除 overflow:hidden，聊天图片中溢出会很明显。
     * 20. 新增字段时优先放入 metrics，不要挤压 handle 区域。
     * 21. rating 数字使用大字号，是整张卡片的主视觉锚点。
     * 22. rank 胶囊高度固定，避免不同 rank 文本导致布局跳动。
     * 23. 指标标签使用较小字号，值使用较大字号，便于快速扫描。
     * 24. 头像区域不显示 alt 文本，图片失败时由 Python 兜底生成缩写。
     * 25. 不要在模板中访问 profile 字段，模板只消费已整理的 data。
     * 26. 修改间距时要同时检查 handle、rank 和品牌区是否重叠。
     * 27. 浅色 tint 只做背景气氛，不承担状态判断。
     * 28. 贡献值和关注数属于辅助指标，不应抢占 rating 主视觉。
     * 29. 未知字段统一展示短占位，避免长错误文本进入卡片。
     * 30. 如需展示更多资料，优先扩展新卡片而不是压缩现有布局。
     */
    /* 固定画布尺寸，配合 OPTIONS.clip 输出稳定大小的图片。 */
    * { box-sizing: border-box; }
    html, body {
      width: 760px;
      height: 430px;
      margin: 0;
      overflow: hidden;
      font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      background: #eef2f7;
      color: #172033;
    }
    .card {
      /* 主卡片保留 20px 外边距，避免阴影被截图裁掉。 */
      position: relative;
      width: 720px;
      height: 390px;
      margin: 20px;
      border-radius: 28px;
      overflow: hidden;
      background:
        linear-gradient(135deg, {{ tint }} 0%, #ffffff 42%, #ffffff 100%);
      box-shadow: 0 18px 42px rgba(15, 23, 42, .16);
    }
    .stripe {
      position: absolute;
      inset: 0 auto 0 0;
      width: 12px;
      background: {{ accent }};
    }
    .brand {
      /* 右上角品牌标识保持固定位置，不参与主体信息排版。 */
      position: absolute;
      top: 26px;
      right: 34px;
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 22px;
      font-weight: 800;
    }
    .bars {
      display: grid;
      grid-template-columns: repeat(3, 5px);
      gap: 3px;
      align-items: end;
      height: 28px;
    }
    .bars i { display: block; width: 5px; border-radius: 5px; }
    .bars i:nth-child(1) { height: 19px; background: #f8c845; }
    .bars i:nth-child(2) { height: 28px; background: #5b8def; }
    .bars i:nth-child(3) { height: 13px; background: #ff7043; }
    .brand .code { color: #1f2937; }
    .brand .forces { color: #2d6cdf; }

    .avatar {
      /* 头像优先展示远端图片，缺失时使用 handle 前两位作为占位。 */
      position: absolute;
      left: 54px;
      top: 62px;
      width: 118px;
      height: 118px;
      border-radius: 28px;
      overflow: hidden;
      background: {{ accent }};
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 42px;
      font-weight: 850;
      box-shadow: 0 12px 28px rgba(15, 23, 42, .2);
    }
    .avatar img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .identity {
      /* 用户身份区展示 handle 和 rank，长 handle 会省略号截断。 */
      position: absolute;
      left: 202px;
      top: 70px;
      width: 290px;
    }
    .handle {
      font-size: 44px;
      line-height: 1.05;
      font-weight: 850;
      letter-spacing: .2px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .rank {
      display: block;
      margin-top: 12px;
      max-width: 246px;
      height: 34px;
      line-height: 34px;
      padding: 0 16px;
      border-radius: 999px;
      background: {{ accent }};
      color: #fff;
      font-size: 18px;
      font-weight: 760;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .rating-block {
      /* Rating 是卡片主信息，放在左下区域并使用等级强调色。 */
      position: absolute;
      left: 54px;
      bottom: 56px;
      width: 248px;
      overflow: hidden;
    }
    .rating-label {
      color: #64748b;
      font-size: 18px;
      font-weight: 780;
      letter-spacing: .3px;
      white-space: nowrap;
    }
    .rating-value {
      margin-top: 4px;
      color: {{ accent }};
      font-size: 68px;
      line-height: .92;
      font-weight: 880;
      letter-spacing: -1px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .level {
      margin-top: 6px;
      color: #334155;
      font-size: 23px;
      line-height: 1.1;
      font-weight: 820;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .metrics {
      /* 四个指标使用 2x2 网格，保证信息密度和可读性平衡。 */
      position: absolute;
      right: 34px;
      bottom: 62px;
      width: 352px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }
    .metric {
      height: 66px;
      border: 1px solid #e2e8f0;
      border-radius: 18px;
      background: rgba(248, 250, 252, .86);
      padding: 10px 14px;
      overflow: hidden;
    }
    .metric .label {
      color: #94a3b8;
      font-size: 13px;
      line-height: 1.1;
      font-weight: 800;
      letter-spacing: .45px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .metric .value {
      margin-top: 6px;
      color: #1e293b;
      font-size: 22px;
      line-height: 1;
      font-weight: 840;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .watermark {
      /* 水印固定在右下角，避免和指标区抢占视觉层级。 */
      position: absolute;
      right: 34px;
      bottom: 20px;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      max-width: 240px;
      padding: 7px 12px;
      border: 1px solid #e2e8f0;
      border-radius: 999px;
      background: rgba(255, 255, 255, .78);
      box-shadow: 0 8px 20px rgba(15, 23, 42, .06);
      color: #475569;
      font-size: 14px;
      line-height: 1;
      font-weight: 760;
    }
    .watermark svg {
      width: 16px;
      height: 16px;
      flex: none;
      fill: #111827;
    }
    .watermark .gh-label {
      color: #334155;
      white-space: nowrap;
    }
    .watermark .sep {
      color: #94a3b8;
      font-weight: 700;
    }
    .watermark .gh-name {
      min-width: 0;
      color: #0f172a;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
  </style>
</head>
<body>
  <div class="card">
    <!-- 装饰边条和品牌区：体现 Codeforces 身份，不承载业务数据。 -->
    <div class="stripe"></div>
    <div class="brand">
      <span class="bars"><i></i><i></i><i></i></span>
      <span><span class="code">Code</span><span class="forces">Forces</span></span>
    </div>

    <!-- 主体身份区：头像、handle、rank 和当前 rating。 -->
    <div class="avatar">{{ avatar_content }}</div>

    <div class="identity">
      <div class="handle">{{ handle }}</div>
      <div class="rank">{{ rank }}</div>
    </div>

    <div class="rating-block">
      <div class="rating-label">当前 Rating</div>
      <div class="rating-value">{{ rating }}</div>
      <div class="level">{{ level }}</div>
    </div>

    <div class="metrics">
      <!-- 指标区：最高 rating、贡献、关注数和最近在线时间。 -->
      {% for item in metrics %}
      <div class="metric">
        <div class="label">{{ item.label }}</div>
        <div class="value">{{ item.value }}</div>
      </div>
      {% endfor %}
    </div>

    <div class="watermark" aria-label="GitHub watermark">
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.5-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.65 7.65 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
      </svg>
      <span class="gh-label">GitHub</span>
      <span class="sep">/</span>
      <span class="gh-name">Brick0411</span>
    </div>
  </div>
</body>
</html>
"""

    RANK_THEME = {
        "newbie": ("#8f98a3", "#f3f4f6"),
        "pupil": ("#1fa14a", "#ecfdf3"),
        "specialist": ("#03a89e", "#ecfeff"),
        "expert": ("#2b6fd6", "#eff6ff"),
        "candidate master": ("#aa43b5", "#fdf4ff"),
        "master": ("#ff8c00", "#fff7ed"),
        "international master": ("#ff8c00", "#fff7ed"),
        "grandmaster": ("#e53935", "#fff1f2"),
        "international grandmaster": ("#e53935", "#fff1f2"),
        "legendary grandmaster": ("#df1f23", "#fff1f2"),
    }

    def build(self, profile: CodeforcesUserProfile) -> tuple[str, dict, dict]:
        """构造 AstrBot html_render 所需的模板、数据和截图参数。"""
        accent, tint = self._rank_theme(profile.rank)
        metrics = [
            {"label": "最高 Rating", "value": self._escape(self._value(profile.max_rating))},
            {"label": "贡献值", "value": self._escape(self._signed_value(profile.contribution))},
            {"label": "关注数", "value": self._escape(self._value(profile.friend_of_count))},
            {"label": "最近在线", "value": self._escape(self._format_time(profile.last_online_time_seconds))},
        ]
        data = {
            "accent": accent,
            "tint": tint,
            "handle": self._escape(profile.handle),
            "rank": self._escape(self._value(profile.rank, "unrated")),
            "rating": self._escape(self._value(profile.rating)),
            "level": self._escape(self._level(profile.rank)),
            "avatar_content": self._avatar_content(profile),
            "metrics": metrics,
        }
        return self.TEMPLATE, data, self.OPTIONS

    @classmethod
    def _rank_theme(cls, rank: str | None) -> tuple[str, str]:
        """根据 Codeforces rank 选择强调色和背景浅色。"""
        return cls.RANK_THEME.get((rank or "unrated").casefold(), ("#64748b", "#f8fafc"))

    def _avatar_content(self, profile: CodeforcesUserProfile) -> str:
        # Codeforces API 同时提供 avatar 和 titlePhoto。
        # titlePhoto 通常更清晰，因此优先用于卡片头像。
        avatar = self._normalize_avatar(
            getattr(profile, "title_photo", None)
            or getattr(profile, "titlePhoto", None)
            or getattr(profile, "avatar", None)
        )
        if avatar:
            return f'<img src="{self._escape(avatar)}" alt="" />'
        return self._escape(profile.handle[:2].upper())

    @staticmethod
    def _level(rank: str | None) -> str:
        """把完整 rank 文本压缩成卡片底部适合展示的等级标签。"""
        rank = (rank or "unrated").casefold()
        aliases = {
            "legendary grandmaster": "LGM",
            "international grandmaster": "IGM",
            "grandmaster": "GM",
            "international master": "IM",
            "candidate master": "CM",
            "specialist": "SPECIALIST",
            "unrated": "UNRATED",
        }
        return aliases.get(rank, rank.upper() if rank else "UNRATED")

    @staticmethod
    def _normalize_avatar(avatar_url: str | None) -> str | None:
        """补全 Codeforces 返回的协议相对头像 URL。"""
        if not avatar_url:
            return None
        if avatar_url.startswith("//"):
            return f"https:{avatar_url}"
        return avatar_url

    @staticmethod
    def _value(value, default: str = "-") -> str:
        return str(value) if value is not None else default

    @staticmethod
    def _signed_value(value: int | None) -> str:
        """贡献值为正时显式补 +，更贴近 Codeforces 展示习惯。"""
        if value is None:
            return "-"
        return f"+{value}" if value > 0 else str(value)

    @staticmethod
    def _format_time(seconds: int | None) -> str:
        if seconds is None:
            return "unknown"
        return datetime.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d")

    @staticmethod
    def _escape(value: str) -> str:
        """转义进入 HTML 模板的文本，避免特殊字符破坏 DOM。"""
        return html.escape(value, quote=True)
