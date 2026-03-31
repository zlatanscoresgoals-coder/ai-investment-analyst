"""Live-ish market quotes (not SEC filings). Used for dashboard context only."""

import csv
import io
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from app.config import settings

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
STOOQ_CSV = "https://stooq.com/q/l/"
FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote"


def _yahoo_symbol(ticker: str) -> str:
    t = ticker.upper().strip()
    if t == "BRK-B":
        return "BRK-B"
    return t.replace(".", "-")


def _stooq_symbol(ticker: str) -> str:
    return ticker.lower().strip().replace(".", "-") + ".us"


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/csv,application/json,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _fetch_finnhub(ticker: str) -> Optional[dict[str, Any]]:
    key = (settings.finnhub_api_key or "").strip()
    if not key:
        return None
    sym = _yahoo_symbol(ticker)
    try:
        r = requests.get(
            FINNHUB_QUOTE,
            params={"symbol": sym, "token": key},
            headers=_browser_headers(),
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None
    c = data.get("c")
    if c is None or c == 0:
        return None
    pc = data.get("pc")
    dp = data.get("dp")
    t = data.get("t")
    as_of = datetime.fromtimestamp(int(t), tz=timezone.utc) if t else datetime.now(timezone.utc)
    change_pct = float(dp) if dp is not None else None
    if change_pct is None and pc and float(pc) != 0:
        change_pct = ((float(c) - float(pc)) / float(pc)) * 100.0
    return {
        "symbol": sym,
        "last_price": round(float(c), 4),
        "currency": "USD",
        "change_pct_day": round(change_pct, 2) if change_pct is not None else None,
        "as_of": as_of.isoformat(),
        "source": "finnhub",
    }


def _fetch_yahoo(ticker: str) -> Optional[dict[str, Any]]:
    sym = _yahoo_symbol(ticker)
    try:
        r = requests.get(
            YAHOO_CHART.format(ticker=requests.utils.quote(sym)),
            headers=_browser_headers(),
            params={"interval": "1d", "range": "5d"},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None

    try:
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        prev = meta.get("previousClose")
        currency = meta.get("currency", "USD")
        ts = meta.get("regularMarketTime")
        if ts:
            as_of = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        else:
            as_of = datetime.now(timezone.utc)

        change_pct = None
        if price is not None and prev and prev != 0:
            change_pct = ((float(price) - float(prev)) / float(prev)) * 100.0

        if price is None:
            return None

        return {
            "symbol": sym,
            "last_price": round(float(price), 4),
            "currency": currency,
            "change_pct_day": round(change_pct, 2) if change_pct is not None else None,
            "as_of": as_of.isoformat(),
            "source": "yahoo_finance_chart",
        }
    except Exception:
        return None


def _fetch_stooq(ticker: str) -> Optional[dict[str, Any]]:
    sym = _stooq_symbol(ticker)
    try:
        r = requests.get(
            STOOQ_CSV,
            params={"s": sym, "i": "d"},
            headers=_browser_headers(),
            timeout=12,
        )
        r.raise_for_status()
        text = r.text.strip()
    except Exception:
        return None

    if not text:
        return None

    try:
        reader = csv.reader(io.StringIO(text))
        rows = [row for row in reader if row and any(c.strip() for c in row)]
        if not rows:
            return None
        header = [h.strip().lower() for h in rows[0]]
        if "close" in header:
            data_rows = rows[1:]
        else:
            data_rows = rows
        if not data_rows:
            return None
        last = data_rows[-1]
        if "close" in header:
            row = dict(zip(header, last))
            close_raw = row.get("close", "")
            open_raw = row.get("open", "")
        else:
            # No header: Symbol,Date,Time,Open,High,Low,Close,Volume
            if len(last) < 7:
                return None
            close_raw, open_raw = last[6], last[3]
        if not close_raw or close_raw == "N/D":
            return None
        price = float(close_raw)
        change_pct = None
        if open_raw and open_raw != "N/D":
            o = float(open_raw)
            if o != 0:
                change_pct = ((price - o) / o) * 100.0
        return {
            "symbol": sym,
            "last_price": round(price, 4),
            "currency": "USD",
            "change_pct_day": round(change_pct, 2) if change_pct is not None else None,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "source": "stooq",
        }
    except Exception:
        return None


def fetch_live_quote(ticker: str) -> Optional[dict[str, Any]]:
    """
    Returns last price, day change %, currency, and quote time.
    Tries Finnhub (if key set), then Yahoo, then Stooq (often works from cloud hosts).
    """
    for fn in (_fetch_finnhub, _fetch_yahoo, _fetch_stooq):
        q = fn(ticker)
        if q:
            return q
    return None
