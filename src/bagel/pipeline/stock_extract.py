"""Stock news enrichment — tickers, themes, sentiment (deterministic)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bagel.pipeline.stock_category import classify_stock
from bagel.pipeline.textutil import strip_html

EXTRACTOR_VERSION = "stock-extract-v1"

# Popular US symbols (avoid bare short words like "IT", "A", "FOR").
_US_TICKERS: dict[str, str] = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Alphabet",
    "GOOG": "Alphabet",
    "AMZN": "Amazon",
    "META": "Meta",
    "NVDA": "NVIDIA",
    "TSLA": "Tesla",
    "NFLX": "Netflix",
    "AMD": "AMD",
    "INTC": "Intel",
    "IBM": "IBM",
    "ORCL": "Oracle",
    "CRM": "Salesforce",
    "AVGO": "Broadcom",
    "QCOM": "Qualcomm",
    "COST": "Costco",
    "JPM": "JPMorgan",
    "BAC": "Bank of America",
    "GS": "Goldman Sachs",
    "V": "Visa",
    "MA": "Mastercard",
    "WMT": "Walmart",
    "DIS": "Disney",
    "BA": "Boeing",
    "XOM": "Exxon",
    "CVX": "Chevron",
    "SPY": "SPDR S&P 500",
    "QQQ": "Invesco QQQ",
    "IWM": "Russell 2000 ETF",
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
}

# CN / HK aliases → Yahoo-style symbol when possible.
_CN_ALIASES: tuple[tuple[str, str, str, str], ...] = (
    ("贵州茅台", "600519.SS", "贵州茅台", "CN"),
    ("茅台", "600519.SS", "贵州茅台", "CN"),
    ("宁德时代", "300750.SZ", "宁德时代", "CN"),
    ("比亚迪", "002594.SZ", "比亚迪", "CN"),
    ("中国平安", "601318.SS", "中国平安", "CN"),
    ("招商银行", "600036.SS", "招商银行", "CN"),
    ("中芯国际", "688981.SS", "中芯国际", "CN"),
    ("寒武纪", "688256.SS", "寒武纪", "CN"),
    ("腾讯", "0700.HK", "腾讯控股", "HK"),
    ("阿里巴巴", "9988.HK", "阿里巴巴", "HK"),
    ("美团", "3690.HK", "美团", "HK"),
    ("小米", "1810.HK", "小米集团", "HK"),
    ("京东", "9618.HK", "京东集团", "HK"),
    ("台积电", "TSM", "台积电", "US"),
    ("英伟达", "NVDA", "NVIDIA", "US"),
    ("苹果", "AAPL", "Apple", "US"),
    ("特斯拉", "TSLA", "Tesla", "US"),
    ("微软", "MSFT", "Microsoft", "US"),
)

_THEME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("降息/宽松", ("降息", "rate cut", "easing", "宽松", "dovish")),
    ("加息/紧缩", ("加息", "rate hike", "tightening", "鹰派", "hawkish")),
    ("通胀/物价", ("通胀", "inflation", "cpi", "ppi", "物价")),
    ("财报季", ("财报", "earnings", "业绩", "营收", "指引", "guidance")),
    ("半导体", ("半导体", "芯片", "chip", "semiconductor", "晶圆", "台积电")),
    ("新能源", ("新能源", "光伏", "锂电", "储能", "ev", "电动车")),
    ("地产", ("房地产", "地产", "房企", "楼市", "按揭")),
    ("银行保险", ("银行", "保险", "券商", "金融股")),
    ("监管政策", ("监管", "证监会", "sec", "反垄断", "合规", "制裁")),
    ("并购重组", ("并购", "收购", "收购", "重组", "私有化")),
    ("宏观数据", ("非农", "gdp", "失业率", "pmi", "零售销售")),
    ("原油大宗", ("原油", "黄金", "大宗", "oil", "gold", "商品")),
)

_BULLISH = (
    "大涨",
    "上涨",
    "飙升",
    "创新高",
    "超预期",
    "看涨",
    "利好",
    "rally",
    "surge",
    "soar",
    "beat",
    "upgrade",
    "bullish",
    "record high",
)
_BEARISH = (
    "大跌",
    "下跌",
    "暴跌",
    "创新低",
    "不及预期",
    "看空",
    "利空",
    "plunge",
    "slump",
    "crash",
    "miss",
    "downgrade",
    "bearish",
    "sell-off",
    "selloff",
)

_CN_CODE_RE = re.compile(r"(?<!\d)([036]\d{5})(?:\.(SS|SZ|SH))?")
_DOLLAR_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")
_US_WORD_RE = re.compile(r"\b([A-Z]{2,5})\b")


@dataclass
class StockTicker:
    symbol: str
    name: str = ""
    exchange: str = "US"

    def as_dict(self) -> dict[str, str]:
        return {"symbol": self.symbol, "name": self.name, "exchange": self.exchange}


@dataclass
class StockEnrichment:
    tickers: list[StockTicker] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    sentiment: str = "neutral"  # bullish | bearish | neutral | mixed
    sentiment_score: float = 0.0
    category: str = "其他"
    extractor_version: str = EXTRACTOR_VERSION

    def as_metadata(self) -> dict[str, Any]:
        return {
            "tickers": [t.as_dict() for t in self.tickers],
            "themes": list(self.themes),
            "sentiment": self.sentiment,
            "sentiment_score": self.sentiment_score,
            "extracted_at": datetime.now(UTC).isoformat(),
            "extractor_version": self.extractor_version,
        }

    def tag_labels(self) -> list[str]:
        labels: list[str] = []
        for t in self.tickers[:6]:
            labels.append(t.symbol)
        for th in self.themes[:4]:
            labels.append(th)
        if self.sentiment and self.sentiment != "neutral":
            labels.append({"bullish": "偏多", "bearish": "偏空", "mixed": "分歧"}.get(self.sentiment, self.sentiment))
        return labels


def enrich_stock_text(title: str, summary: str | None = None) -> StockEnrichment:
    raw = f"{strip_html(title)}\n{strip_html(summary)}"
    text = raw.lower()
    tickers = _extract_tickers(raw, text)
    themes = _extract_themes(text)
    sentiment, score = _score_sentiment(text)
    category = classify_stock(title, summary)
    return StockEnrichment(
        tickers=tickers,
        themes=themes,
        sentiment=sentiment,
        sentiment_score=score,
        category=category,
    )


def merge_stock_metadata(existing: dict[str, Any] | None, enrichment: StockEnrichment) -> dict[str, Any]:
    meta = dict(existing or {})
    meta["domain"] = "stock"
    meta["stock"] = enrichment.as_metadata()
    return meta


def _extract_tickers(raw: str, text_lower: str) -> list[StockTicker]:
    found: dict[str, StockTicker] = {}

    for alias, symbol, name, exchange in _CN_ALIASES:
        if alias.lower() in text_lower or alias in raw:
            found[symbol] = StockTicker(symbol=symbol, name=name, exchange=exchange)

    for m in _CN_CODE_RE.finditer(raw.upper()):
        code = m.group(1)
        suf = (m.group(2) or "").upper()
        if code.startswith("6") or suf in {"SS", "SH"}:
            symbol = f"{code}.SS"
            exchange = "CN"
        elif code.startswith(("0", "3")) or suf == "SZ":
            symbol = f"{code}.SZ"
            exchange = "CN"
        else:
            continue
        found.setdefault(symbol, StockTicker(symbol=symbol, name=code, exchange=exchange))

    for m in _DOLLAR_TICKER_RE.finditer(raw.upper()):
        sym = m.group(1)
        name = _US_TICKERS.get(sym, sym)
        found[sym] = StockTicker(symbol=sym, name=name, exchange="US")

    for m in _US_WORD_RE.finditer(raw):
        sym = m.group(1)
        if sym in _US_TICKERS:
            found[sym] = StockTicker(symbol=sym, name=_US_TICKERS[sym], exchange="US")

    # Prefer primary names order: CN aliases first via insertion, cap list.
    return list(found.values())[:8]


def _extract_themes(text_lower: str) -> list[str]:
    out: list[str] = []
    for theme, aliases in _THEME_RULES:
        if any(a.lower() in text_lower for a in aliases):
            out.append(theme)
    return out[:6]


def _score_sentiment(text_lower: str) -> tuple[str, float]:
    bull = sum(1 for w in _BULLISH if w in text_lower)
    bear = sum(1 for w in _BEARISH if w in text_lower)
    score = float(bull - bear)
    if bull and bear:
        return "mixed", score
    if bull > bear:
        return "bullish", score
    if bear > bull:
        return "bearish", score
    return "neutral", 0.0
