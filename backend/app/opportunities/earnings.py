"""
Earnings radar — Post-Earnings Announcement Drift (Bernard & Thomas, 1989).

Scans upcoming earnings for the 50-stock universe and flags stocks by
their historical beat/miss pattern combined with MERIDIAN fundamental scores.
Uses only yfinance (free).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _parse_earnings_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if hasattr(value, "to_pydatetime"):
        try:
            dt = value.to_pydatetime()
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    try:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _fetch_earnings(ticker: str) -> Optional[dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        name = info.get("shortName") or info.get("longName") or ticker
        sector = info.get("sector") or ""
        current_price = info.get("currentPrice") or info.get("regularMarketPrice")
        target_price = info.get("targetMeanPrice")

        # Earnings date(s) from calendar
        cal = t.calendar
        earnings_date = None
        earnings_dt = None
        earnings_time = None
        if cal is not None:
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if isinstance(ed, list) and ed:
                    earnings_dt = _parse_earnings_datetime(ed[0])
                elif ed is not None:
                    earnings_dt = _parse_earnings_datetime(ed)
            else:
                try:
                    if hasattr(cal, "iloc"):
                        earnings_dt = _parse_earnings_datetime(cal.iloc[0, 0]) if len(cal) > 0 else None
                except Exception:
                    pass

        if earnings_dt is not None:
            earnings_date = earnings_dt.date().isoformat()
        if earnings_date is None:
            return None

        # Treat date-only midnight values conservatively: once midnight passes,
        # the report is no longer a safe pre-earnings setup without session time.
        ed_dt = earnings_dt
        now = datetime.now(timezone.utc)
        if ed_dt <= now or ed_dt > now + timedelta(days=14):
            return None

        # EPS surprise history (last 4 quarters)
        earnings_hist = t.earnings_history
        surprise_history: list[dict[str, Any]] = []
        beats = 0
        misses = 0

        if earnings_hist is not None and hasattr(earnings_hist, "iterrows"):
            for _, row in earnings_hist.tail(4).iterrows():
                actual = row.get("epsActual")
                est = row.get("epsEstimate")
                surprise_pct = row.get("surprisePercent")
                if actual is not None and est is not None:
                    beat = float(actual) >= float(est)
                    if beat:
                        beats += 1
                    else:
                        misses += 1
                    surprise_history.append({
                        "quarter": str(row.get("quarter", ""))[:10] if row.get("quarter") is not None else None,
                        "actual": float(actual) if actual is not None else None,
                        "estimate": float(est) if est is not None else None,
                        "surprise_pct": round(float(surprise_pct) * 100, 2) if surprise_pct is not None else None,
                        "beat": beat,
                    })
        elif isinstance(earnings_hist, dict):
            for qtr, data in list(earnings_hist.items())[-4:]:
                actual = data.get("epsActual") if isinstance(data, dict) else None
                est = data.get("epsEstimate") if isinstance(data, dict) else None
                if actual is not None and est is not None:
                    beat = float(actual) >= float(est)
                    if beat:
                        beats += 1
                    else:
                        misses += 1
                    surprise_history.append({
                        "quarter": str(qtr),
                        "actual": float(actual),
                        "estimate": float(est),
                        "surprise_pct": round((float(actual) - float(est)) / abs(float(est)) * 100, 2) if float(est) != 0 else None,
                        "beat": beat,
                    })

        # Consensus EPS estimate
        eps_estimate = info.get("forwardEps")

        # Target vs current
        upside_pct = None
        if target_price and current_price and current_price > 0:
            upside_pct = round((target_price - current_price) / current_price * 100, 2)

        return {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "earnings_date": earnings_date,
            "earnings_time": earnings_time,
            "current_price": round(float(current_price), 2) if current_price else None,
            "eps_estimate": round(float(eps_estimate), 2) if eps_estimate else None,
            "target_price": round(float(target_price), 2) if target_price else None,
            "upside_pct": upside_pct,
            "surprise_history": surprise_history,
            "beats": beats,
            "misses": misses,
            "total_quarters": beats + misses,
            "days_until": (ed_dt - now).days,
        }
    except Exception as exc:
        logger.debug("earnings fetch %s: %s", ticker, exc)
        return None


def _assign_flag(item: dict[str, Any], meridian_scores: dict[str, float]) -> dict[str, Any]:
    beats = item.get("beats", 0)
    misses = item.get("misses", 0)
    total = item.get("total_quarters", 0)
    ticker = item["ticker"]
    meridian = meridian_scores.get(ticker)

    item["meridian_score"] = round(meridian, 1) if meridian is not None else None

    if beats >= 3 and total >= 3 and (meridian is None or meridian >= 65):
        item["flag"] = "green"
        item["flag_label"] = "Consistent Beater — Watch for Continuation"
    elif misses >= 2:
        item["flag"] = "red"
        item["flag_label"] = "Caution — Miss Risk"
    else:
        item["flag"] = "amber"
        item["flag_label"] = "Monitor"

    # Pre-earnings setup for green-flagged stocks
    if item["flag"] == "green" and item.get("days_until", 0) >= 0:
        days = item.get("days_until", 0)
        item["setup"] = {
            "entry_window": f"{max(1, days - 7)} to {max(1, days - 2)} days before earnings"
            if days > 2 else "Earnings imminent — elevated risk",
            "risk_note": "Earnings are binary events — position size accordingly (1-3% of portfolio max).",
            "drift_note": "PEAD research shows consistent beaters tend to drift upward for 4-8 weeks post-report.",
        }

    return item


def scan_earnings(universe: list[str], meridian_scores: dict[str, float] | None = None) -> list[dict[str, Any]]:
    if meridian_scores is None:
        meridian_scores = {}

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_earnings, t): t for t in universe}
        for fut in as_completed(futures):
            r = fut.result()
            if r is not None:
                results.append(_assign_flag(r, meridian_scores))

    # Sort: green first, then amber, then red; within each group by days_until
    flag_order = {"green": 0, "amber": 1, "red": 2}
    results.sort(key=lambda r: (flag_order.get(r.get("flag", "amber"), 1), r.get("days_until", 99)))
    return results
