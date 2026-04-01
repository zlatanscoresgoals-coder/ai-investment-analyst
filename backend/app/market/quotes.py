"""Live-ish market quotes (not SEC filings). Used for dashboard context only."""

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_QUOTE_V7 = "https://query1.finance.yahoo.com/v7/finance/quote"
STOOQ_CSV = "https://stooq.com/q/l/"
FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote"
ALPHAVANTAGE_QUOTE = "https://www.alphavantage.co/query"
TWELVE_DATA_PRICE = "https://api.twelvedata.com/price"


def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except (TypeError, ValueError):
        return None


def _yahoo_symbol(ticker: str) -> str:
    t = ticker.upper().strip()
    if t == "BRK-B":
        return "BRK-B"
    return t.replace(".", "-")


def _stooq_symbol(ticker: str) -> str:
    return ticker.lower().strip().replace(".", "-") + ".us"


def _finnhub_symbol(ticker: str) -> str:
    """Finnhub US symbols: class-B shares use a dot (e.g. BRK.B)."""
    t = _yahoo_symbol(ticker)
    if t == "BRK-B":
        return "BRK.B"
    return t


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
    sym = _finnhub_symbol(ticker)
    try:
        r = requests.get(
            FINNHUB_QUOTE,
            params={"symbol": sym, "token": key},
            headers={**_browser_headers(), "X-Finnhub-Token": key},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.debug("finnhub http error %s: %s", sym, exc)
        return None
    if not isinstance(data, dict):
        return None
    if data.get("error"):
        logger.warning("finnhub api error for %s: %s", sym, data.get("error"))
        return None
    c_raw = _safe_float(data.get("c"))
    pc = _safe_float(data.get("pc"))
    price = None
    if c_raw is not None and c_raw > 0:
        price = c_raw
    elif pc is not None and pc > 0:
        price = pc
    if price is None:
        logger.debug("finnhub no price for %s payload keys=%s", sym, list(data.keys())[:12])
        return None
    t_raw = data.get("t")
    as_of = datetime.now(timezone.utc)
    if t_raw is not None:
        try:
            as_of = datetime.fromtimestamp(int(float(t_raw)), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
    dp = _safe_float(data.get("dp"))
    change_pct = dp
    if change_pct is None and pc and pc > 0 and c_raw is not None:
        change_pct = ((c_raw - pc) / pc) * 100.0
    return {
        "symbol": sym,
        "last_price": round(price, 4),
        "currency": "USD",
        "change_pct_day": round(change_pct, 2) if change_pct is not None else None,
        "as_of": as_of.isoformat(),
        "source": "finnhub",
    }


def _fetch_yahoo_quote_v7(ticker: str) -> Optional[dict[str, Any]]:
    sym = _yahoo_symbol(ticker)
    try:
        r = requests.get(
            YAHOO_QUOTE_V7,
            params={"symbols": sym},
            headers=_browser_headers(),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.debug("yahoo v7 quote error %s: %s", sym, exc)
        return None
    result = data.get("quoteResponse", {}).get("result") or []
    if not result:
        return None
    q = result[0]
    price = _safe_float(
        q.get("regularMarketPrice")
        or q.get("postMarketPrice")
        or q.get("preMarketPrice")
        or q.get("regularMarketPreviousClose")
    )
    prev = _safe_float(q.get("regularMarketPreviousClose"))
    if price is None or price <= 0:
        return None
    currency = q.get("currency", "USD")
    ts = q.get("regularMarketTime")
    if ts:
        try:
            as_of = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            as_of = datetime.now(timezone.utc)
    else:
        as_of = datetime.now(timezone.utc)
    change_pct = None
    if prev and prev > 0:
        change_pct = ((price - prev) / prev) * 100.0
    return {
        "symbol": sym,
        "last_price": round(price, 4),
        "currency": currency,
        "change_pct_day": round(change_pct, 2) if change_pct is not None else None,
        "as_of": as_of.isoformat(),
        "source": "yahoo_quote_v7",
    }


def _fetch_yahoo_chart(ticker: str) -> Optional[dict[str, Any]]:
    sym = _yahoo_symbol(ticker)
    try:
        r = requests.get(
            YAHOO_CHART.format(ticker=requests.utils.quote(sym)),
            headers=_browser_headers(),
            params={"interval": "1d", "range": "5d"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.debug("yahoo chart error %s: %s", sym, exc)
        return None

    try:
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        meta = result[0].get("meta", {})
        price = _safe_float(meta.get("regularMarketPrice") or meta.get("previousClose"))
        prev = _safe_float(meta.get("previousClose"))
        currency = meta.get("currency", "USD")
        ts = meta.get("regularMarketTime")
        if ts:
            as_of = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        else:
            as_of = datetime.now(timezone.utc)

        change_pct = None
        if price is not None and prev and prev > 0:
            change_pct = ((price - prev) / prev) * 100.0

        if price is None or price <= 0:
            return None

        return {
            "symbol": sym,
            "last_price": round(price, 4),
            "currency": currency,
            "change_pct_day": round(change_pct, 2) if change_pct is not None else None,
            "as_of": as_of.isoformat(),
            "source": "yahoo_finance_chart",
        }
    except Exception as exc:
        logger.debug("yahoo chart parse %s: %s", sym, exc)
        return None


def _fetch_yfinance(ticker: str) -> Optional[dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError:
        return None
    sym = _yahoo_symbol(ticker)
    try:
        t = yf.Ticker(sym)
        price = None
        fi = getattr(t, "fast_info", None)
        if fi is not None:
            try:
                if isinstance(fi, dict):
                    price = _safe_float(fi.get("lastPrice") or fi.get("last_price"))
                    if price is None or price <= 0:
                        price = _safe_float(fi.get("previousClose") or fi.get("previous_close"))
                else:
                    price = _safe_float(getattr(fi, "last_price", None))
                    if price is None or price <= 0:
                        price = _safe_float(getattr(fi, "previous_close", None))
            except Exception:
                price = None
        if price is None or price <= 0:
            hist = t.history(period="5d", auto_adjust=True)
            if hist is not None and not hist.empty and "Close" in hist.columns:
                price = _safe_float(float(hist["Close"].iloc[-1]))
        if price is None or price <= 0:
            return None
        return {
            "symbol": sym,
            "last_price": round(price, 4),
            "currency": "USD",
            "change_pct_day": None,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "source": "yfinance",
        }
    except Exception as exc:
        logger.debug("yfinance error %s: %s", sym, exc)
        return None


def _fetch_stooq(ticker: str) -> Optional[dict[str, Any]]:
    sym = _stooq_symbol(ticker)
    try:
        r = requests.get(
            STOOQ_CSV,
            params={"s": sym, "i": "d"},
            headers=_browser_headers(),
            timeout=10,
        )
        r.raise_for_status()
        text = r.text.strip()
    except Exception as exc:
        logger.debug("stooq error %s: %s", sym, exc)
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
    except Exception as exc:
        logger.debug("stooq parse %s: %s", sym, exc)
        return None


def _fetch_twelve_data(ticker: str) -> Optional[dict[str, Any]]:
    key = (settings.twelve_data_api_key or "").strip()
    if not key:
        return None
    sym = _yahoo_symbol(ticker)
    try:
        r = requests.get(
            TWELVE_DATA_PRICE,
            params={"symbol": sym, "apikey": key},
            headers=_browser_headers(),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.debug("twelve_data error %s: %s", sym, exc)
        return None
    if not isinstance(data, dict) or data.get("status") == "error":
        logger.warning("twelve_data api message: %s", data.get("message", data))
        return None
    price = _safe_float(data.get("price"))
    if price is None or price <= 0:
        return None
    return {
        "symbol": sym,
        "last_price": round(price, 4),
        "currency": "USD",
        "change_pct_day": None,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "twelve_data",
    }


def _fetch_alphavantage(ticker: str) -> Optional[dict[str, Any]]:
    key = (settings.alphavantage_api_key or "").strip()
    if not key:
        return None
    sym = _yahoo_symbol(ticker)
    try:
        r = requests.get(
            ALPHAVANTAGE_QUOTE,
            params={"function": "GLOBAL_QUOTE", "symbol": sym, "apikey": key},
            headers=_browser_headers(),
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        logger.debug("alphavantage error %s: %s", sym, exc)
        return None
    if isinstance(data, dict) and data.get("Note"):
        logger.warning("alphavantage rate limit or note: %s", str(data.get("Note"))[:120])
        return None
    gq = data.get("Global Quote") or data.get("global quote")
    if not gq or not isinstance(gq, dict):
        return None
    price_raw = gq.get("05. price") or gq.get("05. Price")
    price = _safe_float(price_raw)
    if price is None or price <= 0:
        return None
    prev_raw = gq.get("08. previous close") or gq.get("08. Previous close")
    change_pct = None
    prev = _safe_float(prev_raw)
    if prev and prev > 0:
        change_pct = ((price - prev) / prev) * 100.0
    return {
        "symbol": sym,
        "last_price": round(price, 4),
        "currency": "USD",
        "change_pct_day": round(change_pct, 2) if change_pct is not None else None,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "alphavantage",
    }


_FETCHERS: tuple[tuple[str, Callable[[str], Optional[dict[str, Any]]]], ...] = (
    ("finnhub", _fetch_finnhub),
    ("yahoo_quote_v7", _fetch_yahoo_quote_v7),
    ("yahoo_chart", _fetch_yahoo_chart),
    ("yfinance", _fetch_yfinance),
    ("stooq", _fetch_stooq),
    ("twelve_data", _fetch_twelve_data),
    ("alphavantage", _fetch_alphavantage),
)


def fetch_live_quote(ticker: str) -> Optional[dict[str, Any]]:
    """
    Returns last price, day change %, currency, and quote time.
    Tries Finnhub (if key), Yahoo v7 quote, Yahoo chart, yfinance, Stooq, Twelve Data (if key),
    Alpha Vantage (if key).
    """
    t = (ticker or "").strip()
    if not t:
        return None
    for name, fn in _FETCHERS:
        q = fn(t)
        if q:
            logger.debug("quote %s via %s", t.upper(), q.get("source", name))
            return q
    logger.warning(
        "quote failed for %s (no provider returned a price; set FINNHUB_API_KEY or TWELVE_DATA_API_KEY on Railway)",
        t.upper(),
    )
    return None


def quote_debug_status(ticker: str) -> dict[str, Any]:
    """Which providers are configured and which returned a price (for /health/quote)."""
    t = (ticker or "AAPL").strip()
    out: dict[str, Any] = {
        "ticker": t.upper(),
        "finnhub_configured": bool((settings.finnhub_api_key or "").strip()),
        "twelve_data_configured": bool((settings.twelve_data_api_key or "").strip()),
        "alphavantage_configured": bool((settings.alphavantage_api_key or "").strip()),
        "attempts": [],
    }
    for name, fn in _FETCHERS:
        q = fn(t)
        out["attempts"].append({"provider": name, "ok": q is not None, "source": (q or {}).get("source")})
        if q:
            out["winner"] = q
            break
    else:
        out["winner"] = None
    return out
