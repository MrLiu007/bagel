"""Public market OHLC (read-only) — Yahoo chart API with disk cache."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from bagel.integrations.http import build_http_client
from bagel.settings import Settings, get_settings

CACHE_TTL_SECONDS = 3600


@dataclass
class OhlcBar:
    ts: int  # unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class OhlcSeries:
    symbol: str
    currency: str
    bars: list[OhlcBar]
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "currency": self.currency,
            "error": self.error,
            "bars": [
                {
                    "t": b.ts,
                    "o": b.open,
                    "h": b.high,
                    "l": b.low,
                    "c": b.close,
                    "v": b.volume,
                }
                for b in self.bars
            ],
        }


def fetch_ohlc(
    symbol: str,
    *,
    range_: str = "1mo",
    interval: str = "1d",
    settings: Settings | None = None,
) -> OhlcSeries:
    settings = settings or get_settings()
    sym = (symbol or "").strip().upper()
    if not sym:
        return OhlcSeries(symbol="", currency="", bars=[], error="empty symbol")
    if not settings.enable_stock_market_data:
        return OhlcSeries(symbol=sym, currency="", bars=[], error="market data disabled")

    cached = _read_cache(settings, sym, range_, interval)
    if cached is not None:
        return cached

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
        f"?range={range_}&interval={interval}&includePrePost=false"
    )
    try:
        with build_http_client(settings, timeout=25.0, force_proxy=None) as client:
            resp = client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; AI-bagel/0.3; +research)",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError) as exc:
        return OhlcSeries(symbol=sym, currency="", bars=[], error=str(exc)[:240])

    series = _parse_yahoo(sym, data)
    if series.bars and not series.error:
        _write_cache(settings, sym, range_, interval, series)
    return series


def _parse_yahoo(symbol: str, data: dict[str, Any]) -> OhlcSeries:
    try:
        result = ((data.get("chart") or {}).get("result") or [None])[0]
        if not result:
            err = ((data.get("chart") or {}).get("error") or {})
            return OhlcSeries(
                symbol=symbol,
                currency="",
                bars=[],
                error=str(err.get("description") or "no chart data")[:240],
            )
        meta = result.get("meta") or {}
        currency = str(meta.get("currency") or "")
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        bars: list[OhlcBar] = []
        for i, ts in enumerate(timestamps):
            c = closes[i] if i < len(closes) else None
            if c is None or ts is None:
                continue
            bars.append(
                OhlcBar(
                    ts=int(ts),
                    open=float(opens[i] if i < len(opens) and opens[i] is not None else c),
                    high=float(highs[i] if i < len(highs) and highs[i] is not None else c),
                    low=float(lows[i] if i < len(lows) and lows[i] is not None else c),
                    close=float(c),
                    volume=float(volumes[i] if i < len(volumes) and volumes[i] is not None else 0),
                )
            )
        return OhlcSeries(symbol=symbol, currency=currency, bars=bars)
    except (TypeError, ValueError, KeyError, IndexError) as exc:
        return OhlcSeries(symbol=symbol, currency="", bars=[], error=str(exc)[:240])


def _cache_path(settings: Settings, symbol: str, range_: str, interval: str) -> Path:
    safe = symbol.replace("/", "_").replace("\\", "_")
    root = Path(settings.data_dir) / "market"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{safe}_{range_}_{interval}.json"


def _read_cache(settings: Settings, symbol: str, range_: str, interval: str) -> OhlcSeries | None:
    path = _cache_path(settings, symbol, range_, interval)
    if not path.exists():
        return None
    try:
        if time.time() - path.stat().st_mtime > CACHE_TTL_SECONDS:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        bars = [
            OhlcBar(
                ts=int(b["t"]),
                open=float(b["o"]),
                high=float(b["h"]),
                low=float(b["l"]),
                close=float(b["c"]),
                volume=float(b.get("v") or 0),
            )
            for b in data.get("bars") or []
        ]
        return OhlcSeries(
            symbol=str(data.get("symbol") or symbol),
            currency=str(data.get("currency") or ""),
            bars=bars,
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _write_cache(
    settings: Settings,
    symbol: str,
    range_: str,
    interval: str,
    series: OhlcSeries,
) -> None:
    path = _cache_path(settings, symbol, range_, interval)
    try:
        path.write_text(json.dumps(series.as_dict(), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
