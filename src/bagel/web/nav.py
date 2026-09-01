"""Shared navigation for review / collect / settings pages."""

from __future__ import annotations

NAV_ITEMS: list[tuple[str, str, str]] = [
    ("AI新闻", "/news", "news"),
    ("GitHub项目", "/github", "github"),
    ("论文", "/papers", "papers"),
    ("股票", "/stocks", "stocks"),
    ("自媒体", "/media", "media"),
    ("微信", "/wechat", "wechat"),
    ("汇总", "/briefs", "briefs"),
    ("已收藏", "/favorites", "favorites"),
    ("手动采集", "/collect", "collect"),
    ("系统设置", "/settings", "settings"),
]
