"""
Momentum screener — Jegadeesh & Titman (1993) factor implementation.

Screens a 50-stock large-cap universe and returns the top 5 by composite
momentum score.  Uses only yfinance (free) for price/volume data.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _compute_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0, delta))
        losses.append(max(0, -delta))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _fetch_single(ticker: str) -> Optional[dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        t = yf.Ticker(ticker)
        end = datetime.now()
        start = end - timedelta(days=400)
        hist = t.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if hist is None or len(hist) < 60:
            return None

        closes = hist["Close"].tolist()
        volumes = hist["Volume"].tolist()
        current = closes[-1]

        # Returns
        def _ret(days: int) -> Optional[float]:
            idx = max(0, len(closes) - days - 1)
            if closes[idx] <= 0:
                return None
            return (current / closes[idx] - 1.0) * 100.0

        ret_1m = _ret(21)
        ret_6m = _ret(126)
        ret_12m = _ret(252)

        # 1-month momentum crash filter
        if ret_1m is not None and ret_1m < 0:
            return None

        high_52w = max(closes[-min(252, len(closes)):])
        dist_high = (current / high_52w - 1.0) * 100.0 if high_52w > 0 else None

        # Volume ratio: 20-day avg / 50-day avg
        vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else None
        vol_50 = sum(volumes[-50:]) / 50 if len(volumes) >= 50 else None
        vol_ratio = vol_20 / vol_50 if vol_20 and vol_50 and vol_50 > 0 else None

        rsi = _compute_rsi(closes)

        # Sparkline: last 60 closes
        spark = closes[-60:] if len(closes) >= 60 else closes

        info = t.info or {}
        name = info.get("shortName") or info.get("longName") or ticker
        sector = info.get("sector") or ""

        return {
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "current_price": round(current, 2),
            "ret_1m": round(ret_1m, 2) if ret_1m is not None else None,
            "ret_6m": round(ret_6m, 2) if ret_6m is not None else None,
            "ret_12m": round(ret_12m, 2) if ret_12m is not None else None,
            "high_52w": round(high_52w, 2),
            "dist_high_pct": round(dist_high, 2) if dist_high is not None else None,
            "vol_ratio": round(vol_ratio, 3) if vol_ratio is not None else None,
            "vol_trend": "increasing" if vol_ratio and vol_ratio > 1.05 else "decreasing",
            "rsi": round(rsi, 1) if rsi is not None else None,
            "sparkline": [round(c, 2) for c in spark],
        }
    except Exception as exc:
        logger.debug("momentum fetch %s: %s", ticker, exc)
        return None


def _rank_score(values: list[float], idx: int, max_pts: float) -> float:
    """Percentile rank within the list → scaled to max_pts."""
    n = len(values)
    if n <= 1:
        return max_pts / 2.0
    rank = sorted(values).index(values[idx])
    return rank / (n - 1) * max_pts


def scan_momentum(universe: list[str], top_n: int = 5) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_single, t): t for t in universe}
        for fut in as_completed(futures):
            r = fut.result()
            if r is not None:
                results.append(r)

    if not results:
        return []

    # Score components
    ret6 = [r["ret_6m"] or 0 for r in results]
    ret12 = [r["ret_12m"] or 0 for r in results]
    vols = [r["vol_ratio"] or 1.0 for r in results]

    for i, r in enumerate(results):
        score = 0.0
        score += _rank_score(ret6, i, 30.0)
        score += _rank_score(ret12, i, 25.0)
        score += _rank_score(vols, i, 20.0)

        # RSI in 50-70 range: 15 points
        rsi = r.get("rsi")
        if rsi is not None:
            if 50 <= rsi <= 70:
                score += 15.0
            elif 40 <= rsi < 50 or 70 < rsi <= 80:
                score += 7.0

        # Within 15% of 52-week high: 10 points
        dist = r.get("dist_high_pct")
        if dist is not None and dist >= -15.0:
            score += 10.0
        elif dist is not None and dist >= -25.0:
            score += 4.0

        r["momentum_score"] = round(score, 1)

    results.sort(key=lambda r: r["momentum_score"], reverse=True)
    return results[:top_n]
