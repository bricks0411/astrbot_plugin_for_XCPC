"""Codeforces 用户资料卡片渲染数据构造。"""
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
    <div class="stripe"></div>
    <div class="brand">
      <span class="bars"><i></i><i></i><i></i></span>
      <span><span class="code">Code</span><span class="forces">Forces</span></span>
    </div>

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
