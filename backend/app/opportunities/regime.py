"""
Market regime indicator — Fama-French / AQR factor regime detection.

All data from yfinance (free). No paid APIs.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Optional

from app.opportunities.universe import SECTOR_ETFS

logger = logging.getLogger(__name__)


def _fetch_history(symbol: str, days: int = 300) -> Optional[list[float]]:
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        end = datetime.now()
        start = end - timedelta(days=days)
        hist = yf.Ticker(symbol).history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        if hist is None or len(hist) < 20:
            return None
        return hist["Close"].tolist()
    except Exception as exc:
        logger.debug("regime fetch %s: %s", symbol, exc)
        return None


def _sma(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _pct_above_200ma(universe: list[str]) -> Optional[float]:
    """% of stocks in universe trading above their own 200-day MA."""
    above = 0
    total = 0

    def _check(ticker: str) -> Optional[bool]:
        closes = _fetch_history(ticker, days=300)
        if closes is None or len(closes) < 200:
            return None
        ma200 = sum(closes[-200:]) / 200
        return closes[-1] > ma200

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_check, t): t for t in universe}
        for fut in as_completed(futures):
            r = fut.result()
            if r is not None:
                total += 1
                if r:
                    above += 1

    if total == 0:
        return None
    return round(above / total * 100, 1)


def _sector_performance() -> list[dict[str, Any]]:
    results = []

    def _calc(symbol: str) -> Optional[dict[str, Any]]:
        closes = _fetch_history(symbol, days=65)
        if closes is None or len(closes) < 22:
            return None
        ret_1m = (closes[-1] / closes[-22] - 1.0) * 100.0
        ret_3m = None
        if len(closes) >= 63:
            ret_3m = (closes[-1] / closes[-63] - 1.0) * 100.0
        return {
            "symbol": symbol,
            "sector": SECTOR_ETFS.get(symbol, symbol),
            "ret_1m": round(ret_1m, 2),
            "ret_3m": round(ret_3m, 2) if ret_3m is not None else None,
        }

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_calc, s): s for s in SECTOR_ETFS}
        for fut in as_completed(futures):
            r = fut.result()
            if r is not None:
                results.append(r)

    results.sort(key=lambda r: r["ret_1m"], reverse=True)
    return results


def scan_regime(universe: list[str]) -> dict[str, Any]:
    # SPY analysis
    spy_closes = _fetch_history("SPY", days=300)
    spy_current = spy_closes[-1] if spy_closes else None
    spy_ma50 = _sma(spy_closes, 50) if spy_closes else None
    spy_ma200 = _sma(spy_closes, 200) if spy_closes else None
    spy_above_200 = (spy_current > spy_ma200) if spy_current and spy_ma200 else None

    # Golden/death cross detection
    cross_signal = None
    if spy_ma50 is not None and spy_ma200 is not None:
        if spy_ma50 > spy_ma200:
            cross_signal = "golden_cross"
        else:
            cross_signal = "death_cross"

    # SPY trend direction: simple slope of last 20 days
    trend = "sideways"
    if spy_closes and len(spy_closes) >= 20:
        recent_20 = spy_closes[-20:]
        slope = (recent_20[-1] - recent_20[0]) / recent_20[0] * 100
        if slope > 2:
            trend = "uptrend"
        elif slope < -2:
            trend = "downtrend"

    # VIX
    vix_closes = _fetch_history("^VIX", days=30)
    vix_current = round(vix_closes[-1], 2) if vix_closes else None
    vix_label = "unknown"
    if vix_current is not None:
        if vix_current < 15:
            vix_label = "low"
        elif vix_current <= 25:
            vix_label = "normal"
        elif vix_current <= 35:
            vix_label = "elevated"
        else:
            vix_label = "panic"

    # Market breadth
    breadth = _pct_above_200ma(universe)

    # Credit proxy: XLF vs SPY relative performance (1 month)
    xlf_closes = _fetch_history("XLF", days=30)
    credit_signal = None
    if xlf_closes and spy_closes and len(xlf_closes) >= 22 and len(spy_closes) >= 22:
        xlf_ret = (xlf_closes[-1] / xlf_closes[-22] - 1.0) * 100.0
        spy_ret = (spy_closes[-1] / spy_closes[-22] - 1.0) * 100.0
        credit_signal = round(xlf_ret - spy_ret, 2)

    # Sector rotation
    sectors = _sector_performance()

    # Regime determination
    bull_signals = 0
    bear_signals = 0
    if spy_above_200:
        bull_signals += 2
    elif spy_above_200 is False:
        bear_signals += 2
    if cross_signal == "golden_cross":
        bull_signals += 1
    elif cross_signal == "death_cross":
        bear_signals += 1
    if vix_current is not None:
        if vix_current < 20:
            bull_signals += 1
        elif vix_current > 30:
            bear_signals += 2
        elif vix_current > 25:
            bear_signals += 1
    if breadth is not None:
        if breadth > 60:
            bull_signals += 1
        elif breadth < 40:
            bear_signals += 1
    if trend == "uptrend":
        bull_signals += 1
    elif trend == "downtrend":
        bear_signals += 1

    if bull_signals >= 4 and bear_signals <= 1:
        regime = "bull"
        regime_label = "BULL MARKET — MOMENTUM FAVORED"
        favored = "Momentum"
        overweight = "Wood (growth) and Ackman (quality momentum) lenses"
        underweight = "Burry (deep value) lens — limited upside capture in strong trends"
    elif bear_signals >= 4 and bull_signals <= 1:
        regime = "bear"
        regime_label = "BEAR MARKET — DEFENSIVE FAVORED"
        favored = "Defensive / Value"
        overweight = "Burry (balance sheet safety) and Buffett (quality moat) lenses"
        underweight = "Wood (growth) lens — high-growth names most vulnerable in downturns"
    else:
        regime = "transition"
        regime_label = "TRANSITIONING — QUALITY FAVORED"
        favored = "Quality"
        overweight = "Buffett (quality/moat) and Institutional (earnings quality) lenses"
        underweight = "Pure momentum plays — factor crashes most likely during transitions"

    return {
        "regime": regime,
        "regime_label": regime_label,
        "favored_strategy": favored,
        "overweight": overweight,
        "underweight": underweight,
        "spy_current": round(spy_current, 2) if spy_current else None,
        "spy_ma50": round(spy_ma50, 2) if spy_ma50 else None,
        "spy_ma200": round(spy_ma200, 2) if spy_ma200 else None,
        "spy_above_200ma": spy_above_200,
        "cross_signal": cross_signal,
        "trend": trend,
        "vix_current": vix_current,
        "vix_label": vix_label,
        "breadth_pct": breadth,
        "credit_signal": credit_signal,
        "sectors": sectors,
        "bull_signals": bull_signals,
        "bear_signals": bear_signals,
        "scanned_at": datetime.now().isoformat(),
    }
