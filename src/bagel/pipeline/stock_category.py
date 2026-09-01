"""Fixed taxonomy for stock / market news."""

from __future__ import annotations

from bagel.pipeline.textutil import strip_html

STOCK_CATEGORIES: tuple[str, ...] = (
    "宏观政策",
    "个股动态",
    "板块轮动",
    "财报业绩",
    "监管合规",
    "大宗商品",
    "汇率利率",
    "市场情绪",
    "其他",
)

_ALIAS_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "宏观政策",
        ("降息", "加息", "财政", "货币政策", "刺激", "非农", "gdp", "美联储", "央行", "policy"),
    ),
    (
        "财报业绩",
        ("财报", "earnings", "业绩", "营收", "净利润", "指引", "guidance", "季报", "年报"),
    ),
    (
        "监管合规",
        ("监管", "证监会", "sec", "反垄断", "制裁", "合规", "调查", "罚款"),
    ),
    (
        "大宗商品",
        ("原油", "黄金", "铜", "铁矿", "大宗", "oil", "gold", "commodity"),
    ),
    (
        "汇率利率",
        ("汇率", "人民币", "美元", "国债", "yield", "利率", "外汇", "forex"),
    ),
    (
        "板块轮动",
        ("半导体", "新能源", "银行", "地产", "消费", "科技股", "板块", "sector", "轮动"),
    ),
    (
        "个股动态",
        ("股份", "公司", "股价", "stock", "ipo", "回购", "增持", "减持", "拆股"),
    ),
    (
        "市场情绪",
        ("恐慌", "贪婪", "情绪", "波动", "volatility", "vix", "risk-on", "risk-off"),
    ),
)


def classify_stock(title: str, summary: str | None = None) -> str:
    text = f"{strip_html(title)}\n{strip_html(summary)}".lower()
    best: str | None = None
    best_len = -1
    for category, aliases in _ALIAS_GROUPS:
        for alias in aliases:
            needle = alias.lower()
            if needle in text and len(needle) > best_len:
                best = category
                best_len = len(needle)
    return best or "其他"


def list_stock_categories() -> list[str]:
    return list(STOCK_CATEGORIES)
