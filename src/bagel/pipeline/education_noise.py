"""Reject site chrome / boilerplate pages from education collectors."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Exact titles (after strip) that are never intel.
_EXACT_TITLES = frozenset(
    {
        "首页",
        "更多",
        "更多>>",
        "更多>",
        "返回",
        "返回首页",
        "上一页",
        "下一页",
        "尾页",
        "登录",
        "考生登录",
        "管理人员登录",
        "联系我们",
        "联系方式",
        "网站地图",
        "网站声明",
        "版权声明",
        "法律声明",
        "免责声明",
        "隐私政策",
        "隐私保护",
        "使用帮助",
        "帮助中心",
        "设为首页",
        "加入收藏",
        "收藏本站",
        "回到顶部",
        "关闭",
        "打印",
        "打印本页",
        "分享",
        "分享到",
        "手机版",
        "移动版",
        "旧版网站",
        "无障碍",
        "无障碍浏览",
        "繁體",
        "繁体",
        "English",
        "EN",
        "RSS",
        "友情链接",
        "相关链接",
        "栏目导航",
        "当前位置",
        "网站标识码",
        "我要纠错",
        "技术支持",
        "主办单位",
        "承办单位",
        "版权所有",
        "关于我们",
        "站点地图",
        "站长统计",
        "政府网站年检",
        "备案查询",
        "博士",
        "硕士",
        "港澳台",
    }
)

# Title contains these → chrome (short titles only, or always for strong markers).
_TITLE_CONTAINS = (
    "网站声明",
    "网站地图",
    "站点地图",
    "联系我们",
    "版权所有",
    "ICP备",
    "京ICP",
    "津ICP",
    "沪ICP",
    "粤ICP",
    "无障碍浏览",
    "政府网站标识码",
)

# MOE footer chrome lives under these column ids but still uses t20… article URLs.
_URL_PATH_NOISE = (
    "/jyb_sy/s3634/",  # 网站声明
    "/jyb_sy/s3635/",  # 联系我们
    "/jyb_sy/s3636/",  # 网站地图
    "/sitemap",
    "/contact",
    "/aboutus",
    "/about_us",
    "/privacy",
    "/copyright",
    "/wzsm",
    "/wzdh",
    "/lxwm",
)

_MIN_TITLE_LEN = 4


def is_education_noise(title: str | None, url: str | None = None) -> bool:
    """True when the row is site chrome / legal / nav, not substantive intel."""
    text = re.sub(r"\s+", " ", (title or "").strip())
    if not text:
        return True
    if len(text) < _MIN_TITLE_LEN:
        return True
    if text in _EXACT_TITLES:
        return True
    # Exact-ish: title is only chrome words (+ punctuation).
    compact = re.sub(r"[\s\-_|·•/\\]+", "", text)
    if compact in {re.sub(r"[\s\-_|·•/\\]+", "", t) for t in _EXACT_TITLES}:
        return True
    for needle in _TITLE_CONTAINS:
        if needle in text and len(text) <= len(needle) + 6:
            return True

    raw_url = (url or "").strip()
    if not raw_url:
        return False
    low = raw_url.lower()
    if any(p in low for p in _URL_PATH_NOISE):
        return True
    try:
        path = (urlparse(raw_url).path or "").lower()
    except Exception:
        path = low
    # Bare section indexes, not article bodies.
    if path.rstrip("/").endswith(
        ("/index", "/index.htm", "/index.html", "/index.shtml", "/default.htm")
    ):
        return True
    return False


def filter_education_records(records: list) -> list:
    """Drop noise rows from a list of EducationRecord-like objects."""
    return [
        r
        for r in records
        if not is_education_noise(getattr(r, "title", None), getattr(r, "url", None))
    ]
