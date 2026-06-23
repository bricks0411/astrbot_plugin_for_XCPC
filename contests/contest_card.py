"""Codeforces 比赛卡片渲染数据构造。"""
from __future__ import annotations

import datetime
import html

from .models import CodeforcesContestInfoResult, CodeforcesContestProfile


class ContestCardRenderer:
    """构造 Codeforces 比赛信息卡片的 HTML 模板数据。"""

    WIDTH = 860

    OUTER_MARGIN = 20
    TOPBAR_HEIGHT = 112
    LIST_PADDING_TOP = 18
    LIST_PADDING_BOTTOM = 0
    ROW_MIN_HEIGHT = 102
    ROW_GAP = 14
    FOOTER_HEIGHT = 64
    EMPTY_HEIGHT = 102

    PHASE_THEME = {
        "BEFORE": {
            "text": "#15803d",
            "bg": "#dcfce7",
            "border": "#86efac",
            "accent": "#16a34a",
        },
        "CODING": {
            "text": "#a16207",
            "bg": "#fef3c7",
            "border": "#fde68a",
            "accent": "#eab308",
        },
        "PENDING_SYSTEM_TEST": {
            "text": "#c2410c",
            "bg": "#ffedd5",
            "border": "#fed7aa",
            "accent": "#f97316",
        },
        "SYSTEM_TEST": {
            "text": "#1d4ed8",
            "bg": "#dbeafe",
            "border": "#93c5fd",
            "accent": "#3b82f6",
        },
        "FINISHED": {
            "text": "#dc2626",
            "bg": "#fee2e2",
            "border": "#fecaca",
            "accent": "#ef4444",
        },
        "FINISH": {
            "text": "#dc2626",
            "bg": "#fee2e2",
            "border": "#fecaca",
            "accent": "#ef4444",
        },
    }

    DEFAULT_PHASE_THEME = {
        "text": "#475569",
        "bg": "#f1f5f9",
        "border": "#cbd5e1",
        "accent": "#64748b",
    }

    PHASE_TEXT = {
        "BEFORE": "未开始",
        "CODING": "进行中",
        "PENDING_SYSTEM_TEST": "等待系统测试",
        "SYSTEM_TEST": "系统测试中",
        "FINISHED": "已结束",
        "FINISH": "已结束",
        "UNKNOWN": "未知状态",
    }

    TYPE_TEXT = {
        "CF": "官方赛",
        "ICPC": "ICPC",
        "IOI": "IOI",
    }

    TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width={{ width }}, initial-scale=1" />
  <style>
    * { box-sizing: border-box; }
    html {
      width: {{ width }}px;
      min-width: {{ width }}px;
      margin: 0;
      padding: 0;
      overflow: visible;
      background: #eef2f7;
    }
    body {
      width: {{ width }}px;
      min-width: {{ width }}px;
      min-height: {{ min_height }}px;
      margin: 0;
      padding: 0;
      overflow: visible;
      font-family: "Segoe UI", "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif;
      background: #eef2f7;
      color: #182033;
    }
    .board {
      /* 主卡片作为唯一外框，内部列表通过 flex 垂直排布。 */
      width: calc(100% - 40px);
      min-height: calc({{ min_height }}px - 40px);
      margin: 20px;
      border-radius: 24px;
      overflow: hidden;
      background: #ffffff;
      box-shadow: 0 18px 42px rgba(15, 23, 42, .16);
      display: flex;
      flex-direction: column;
    }
    .topbar {
      /* 顶部区域承载标题、摘要和 Codeforces 标识。 */
      position: relative;
      flex: none;
      height: 112px;
      padding: 28px 34px 0;
      background:
        radial-gradient(circle at 8% 0%, rgba(239, 68, 68, .16), transparent 35%),
        linear-gradient(135deg, rgba(229, 57, 53, .12), rgba(45, 108, 223, .10) 56%, rgba(255, 255, 255, 0));
      border-bottom: 1px solid #e5eaf2;
    }
    .title {
      margin: 0;
      max-width: 560px;
      font-size: 38px;
      line-height: 1;
      font-weight: 860;
      letter-spacing: 0;
      color: #172033;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .subtitle {
      margin-top: 12px;
      max-width: 560px;
      color: #64748b;
      font-size: 18px;
      line-height: 1.2;
      font-weight: 720;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .brand {
      position: absolute;
      top: 28px;
      right: 34px;
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 25px;
      font-weight: 840;
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
    .code { color: #1f2937; }
    .forces { color: #2d6cdf; }

    .list {
      /* 列表高度由内容决定，full_page 截图会捕获完整 DOM。 */
      flex: none;
      padding: 18px 24px 0;
    }
    .contest {
      /* 每场比赛使用状态色作为左侧强调色，便于快速区分阶段。 */
      --phase-bg: #f1f5f9;
      --phase-text: #475569;
      --phase-border: #cbd5e1;
      --phase-accent: #64748b;

      display: grid;
      grid-template-columns: 66px minmax(0, 1fr) 148px;
      gap: 16px;
      min-height: 102px;
      padding: 16px 16px;
      border: 1px solid #e5eaf2;
      border-left: 6px solid var(--phase-accent);
      border-radius: 18px;
      background:
        linear-gradient(90deg, var(--phase-bg), #f8fafc 36%);
      margin-bottom: 14px;
    }
    .contest:last-child {
      margin-bottom: 0;
    }
    .index {
      width: 54px;
      height: 54px;
      border-radius: 17px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--phase-accent);
      color: #fff;
      font-size: 27px;
      font-weight: 860;
      box-shadow: 0 10px 18px rgba(15, 23, 42, .10);
    }
    .main {
      min-width: 0;
      align-self: center;
    }
    .name {
      margin-top: 0;
      max-width: 500px;
      font-size: 22px;
      line-height: 1.22;
      font-weight: 820;
      color: #172033;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    .meta {
      /* 标签允许换行，避免长比赛名称和多个状态标签互相挤压。 */
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    .pill {
      min-height: 27px;
      padding: 5px 11px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      color: #475569;
      background: #edf2f7;
      border: 1px solid transparent;
      font-size: 14px;
      line-height: 1;
      font-weight: 780;
      white-space: nowrap;
    }
    .pill.phase {
      color: var(--phase-text);
      background: var(--phase-bg);
      border-color: var(--phase-border);
    }
    .side {
      /* 右侧固定宽度展示日期、时间和比赛 ID。 */
      text-align: right;
      align-self: center;
      min-width: 0;
    }
    .date {
      color: #172033;
      font-size: 19px;
      line-height: 1.05;
      font-weight: 840;
      white-space: nowrap;
    }
    .time {
      margin-top: 7px;
      color: #64748b;
      font-size: 17px;
      font-weight: 760;
      white-space: nowrap;
    }
    .link {
      margin-top: 10px;
      color: #2d6cdf;
      font-size: 14px;
      font-weight: 760;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .empty {
      height: 102px;
      border: 1px dashed #cbd5e1;
      border-radius: 18px;
      background: #f8fafc;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #64748b;
      font-size: 18px;
      font-weight: 760;
    }
    .footer {
      /* 页脚贴底显示生成时间和水印，短列表也能保持视觉平衡。 */
      flex: none;
      min-height: 64px;
      margin-top: auto;
      padding: 16px 34px 18px;
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      color: #94a3b8;
      font-size: 15px;
      font-weight: 720;
    }
    .watermark {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      max-width: 260px;
      padding: 7px 12px;
      border: 1px solid #e2e8f0;
      border-radius: 999px;
      background: rgba(255, 255, 255, .82);
      box-shadow: 0 8px 20px rgba(15, 23, 42, .06);
      color: #475569;
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
  <div class="board">
    <!-- 头部摘要区：固定高度，保证不同比赛数量下标题位置稳定。 -->
    <div class="topbar">
      <h1 class="title">比赛信息</h1>
      <div class="subtitle">{{ summary }}</div>
      <div class="brand">
        <span class="bars"><i></i><i></i><i></i></span>
        <span><span class="code">Code</span><span class="forces">Forces</span></span>
      </div>
    </div>

    <div class="list">
      <!-- 比赛列表区：无数据时渲染空状态，有数据时逐条渲染比赛卡片。 -->
      {% if contests %}
      {% for contest in contests %}
      <div class="contest" style="--phase-bg: {{ contest.phase_bg }}; --phase-text: {{ contest.phase_text }}; --phase-border: {{ contest.phase_border }}; --phase-accent: {{ contest.phase_accent }};">
        <div class="index">{{ contest.index }}</div>
        <div class="main">
          <div class="name">{{ contest.name }}</div>
          <div class="meta">
            <span class="pill phase">{{ contest.phase }}</span>
            <span class="pill">{{ contest.type }}</span>
            <span class="pill">{{ contest.duration }}</span>
            {% if contest.before_start %}
            <span class="pill">{{ contest.before_start }}</span>
            {% endif %}
          </div>
        </div>
        <div class="side">
          <div class="date">{{ contest.date }}</div>
          <div class="time">{{ contest.time }}</div>
          <div class="link">比赛 ID：{{ contest.id }}</div>
        </div>
      </div>
      {% endfor %}
      {% else %}
      <div class="empty">暂无比赛信息</div>
      {% endif %}
    </div>

    <div class="footer">
      <span>{{ generated_at }}</span>
      <span class="watermark" aria-label="GitHub watermark">
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.5-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.65 7.65 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
        </svg>
        <span class="gh-label">GitHub</span>
        <span class="sep">/</span>
        <span class="gh-name">Brick0411</span>
      </span>
    </div>
  </div>
</body>
</html>
"""

    def build(self, result: CodeforcesContestInfoResult) -> tuple[str, dict, dict]:
        """构造 AstrBot html_render 所需的模板、数据和截图参数。"""
        contests = result.contests or []
        contest_items = [
            self._build_contest_item(index, contest)
            for index, contest in enumerate(contests, start=1)
        ]
        min_height = self._calculate_min_height(len(contest_items))
        data = {
            "width": self.WIDTH,
            "min_height": min_height,
            "summary": self._escape(result.message),
            "generated_at": datetime.datetime.now().strftime("生成时间：%Y-%m-%d %H:%M:%S"),
            "contests": contest_items,
        }
        options = {
            "full_page": True,
            "type": "png",
            "animations": "disabled",
            "caret": "hide",
            "scale": "css",
            "timeout": 30000,

            "viewport_width": self.WIDTH,
            "viewport_height": max(720, min_height),
            "device_scale_factor_level": "high",
        }
        return self.TEMPLATE, data, options

    @classmethod
    def _calculate_min_height(cls, contest_count: int) -> int:
        """根据比赛数量计算 full_page 截图需要的最小高度。"""
        if contest_count <= 0:
            list_content_height = cls.EMPTY_HEIGHT
        else:
            list_content_height = contest_count * cls.ROW_MIN_HEIGHT
            list_content_height += max(contest_count - 1, 0) * cls.ROW_GAP

        board_height = (
            cls.TOPBAR_HEIGHT
            + cls.LIST_PADDING_TOP
            + cls.LIST_PADDING_BOTTOM
            + list_content_height
            + cls.FOOTER_HEIGHT
        )
        return cls.OUTER_MARGIN * 2 + board_height

    def _build_contest_item(self, index: int, contest: CodeforcesContestProfile) -> dict:
        """把单场比赛模型转换为模板可直接使用的字典。"""
        start_time = self._format_start_time(contest.start_time_seconds)
        phase = self._normalize_phase(contest.phase)
        theme = self._phase_theme(phase)

        return {
            "index": index,
            "id": contest.id,
            "name": self._escape(contest.name),
            "type": self._escape(self._format_type(contest.type)),
            "phase": self._escape(self._format_phase(phase)),
            "duration": self._escape(self._format_duration(contest.duration_seconds)),
            "before_start": self._escape(self._format_before_start(contest.start_time_seconds)),
            "date": start_time[0],
            "time": start_time[1],
            "phase_bg": theme["bg"],
            "phase_text": theme["text"],
            "phase_border": theme["border"],
            "phase_accent": theme["accent"],
        }

    @classmethod
    def _phase_theme(cls, phase: str) -> dict:
        """根据比赛阶段选择状态主题色。"""
        return cls.PHASE_THEME.get(phase, cls.DEFAULT_PHASE_THEME)

    @staticmethod
    def _normalize_phase(phase: str | None) -> str:
        """统一比赛阶段文本，便于映射主题和中文显示。"""
        if not phase:
            return "UNKNOWN"
        return str(phase).strip().upper()

    @classmethod
    def _format_phase(cls, phase: str) -> str:
        return cls.PHASE_TEXT.get(phase, phase)

    @classmethod
    def _format_type(cls, contest_type: str | None) -> str:
        if not contest_type:
            return "未知类型"
        normalized_type = str(contest_type).strip().upper()
        return cls.TYPE_TEXT.get(normalized_type, normalized_type)

    @staticmethod
    def _format_start_time(seconds: int | None) -> tuple[str, str]:
        if seconds is None:
            return "未知日期", "--:--"
        start_time = datetime.datetime.fromtimestamp(seconds)
        return start_time.strftime("%Y-%m-%d"), start_time.strftime("%H:%M")

    @staticmethod
    def _format_duration(seconds: int | None) -> str:
        if seconds is None:
            return "-"
        hours = seconds // 3600
        minutes = seconds % 3600 // 60
        if minutes:
            return f"时长 {hours} 小时 {minutes} 分钟"
        return f"时长 {hours} 小时"

    @staticmethod
    def _format_before_start(seconds: int | None) -> str:
        """生成距离开赛时间的短文本。"""
        if seconds is None:
            return ""
        delta_seconds = seconds - int(datetime.datetime.now().timestamp())
        if delta_seconds <= 0:
            return "已开赛"
        days = delta_seconds // 86400
        hours = delta_seconds % 86400 // 3600
        if days:
            return f"距开赛 {days} 天 {hours} 小时"
        minutes = delta_seconds % 3600 // 60
        return f"距开赛 {hours} 小时 {minutes} 分钟"

    @staticmethod
    def _escape(value: object) -> str:
        """转义进入 HTML 模板的文本，避免特殊字符破坏 DOM。"""
        return html.escape(str(value), quote=True)
