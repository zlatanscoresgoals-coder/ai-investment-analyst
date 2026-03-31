"""Live-ish market quotes (not SEC filings). Used for dashboard context only."""

from datetime import datetime, timezone
from typing import Any, Optional

import requests

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


def _yahoo_symbol(ticker: str) -> str:
    t = ticker.upper().strip()
    if t == "BRK-B":
        return "BRK-B"
    return t.replace(".", "-")


def fetch_live_quote(ticker: str) -> Optional[dict[str, Any]]:
    """
    Returns last price, day change %, currency, and quote time.
    Best-effort; returns None if upstream unavailable.
    """
    sym = _yahoo_symbol(ticker)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AIInvestmentAnalyst/1.0; +https://example.com)",
        "Accept": "application/json",
    }
    try:
        r = requests.get(
            YAHOO_CHART.format(ticker=requests.utils.quote(sym)),
            headers=headers,
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
