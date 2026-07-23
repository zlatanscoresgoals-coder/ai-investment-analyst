"""
Investor-persona scoring functions.

Design principles:
- Every function returns a float in [0, 100].
- Scores are built from sigmoid-style soft thresholds so a metric that just
  misses a bar doesn't cliff-drop to zero; it degrades smoothly.
- Sector-relative context is accepted via the optional `sector` kwarg and
  adjusts the reference thresholds for metrics where industry norms differ
  materially (e.g. gross margin for banks vs software).
- Trend signals (3-year direction) are used as secondary modifiers — they
  can add or subtract up to ~8 points but cannot dominate the snapshot score.
- The Pelosi Proxy has been removed; its 5% weight is redistributed to
  Buffett and Burry (the two most data-grounded lenses).
"""

from __future__ import annotations

import math
from typing import Any, Optional


def _finite_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _metric_or_zero(metrics: dict[str, Any], key: str) -> float:
    return _finite_or_none(metrics.get(key)) or 0.0


def _bounded_contribution(value: Any, multiplier: float, lower: float, upper: float) -> float:
    numeric = _finite_or_none(value)
    if numeric is None:
        return 0.0
    return max(lower, min(upper, numeric * multiplier))


def _clamp(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(100.0, value))


def _soft(value: float, good: float, bad: float, scale: float = 1.0) -> float:
    """
    Smooth score contribution for a metric.
    Returns +scale when value == good, 0 when value == midpoint, -scale at bad.
    Uses a linear interpolation capped at ±scale.
    """
    value = _finite_or_none(value)
    if value is None:
        return 0.0
    span = abs(good - bad)
    if span == 0:
        return 0.0
    raw = (value - (good + bad) / 2.0) / (span / 2.0) * scale
    return max(-scale, min(scale, raw))


# ---------------------------------------------------------------------------
# Sector-relative threshold adjustments
# ---------------------------------------------------------------------------

def _sector_key(sector: Optional[str]) -> str:
    s = (sector or "").lower()
    if any(k in s for k in ("bank", "financ", "insur", "credit")):
        return "financial"
    if any(k in s for k in ("software", "tech", "semiconductor", "internet", "cloud")):
        return "tech"
    if any(k in s for k in ("pharma", "biotech", "health", "medical")):
        return "health"
    if any(k in s for k in ("energy", "oil", "gas", "mining", "material")):
        return "energy"
    if any(k in s for k in ("retail", "consumer", "food", "beverage", "apparel")):
        return "consumer"
    if any(k in s for k in ("util", "electric", "water", "telecom")):
        return "utility"
    return "default"


# Gross margin reference bands by sector (good_threshold, acceptable_threshold)
_GROSS_MARGIN_BANDS: dict[str, tuple[float, float]] = {
    "tech":      (60.0, 40.0),
    "health":    (55.0, 35.0),
    "financial": (50.0, 30.0),   # net interest margin proxy
    "consumer":  (35.0, 20.0),
    "energy":    (30.0, 15.0),
    "utility":   (35.0, 20.0),
    "default":   (45.0, 25.0),
}

# Operating margin reference bands
_OP_MARGIN_BANDS: dict[str, tuple[float, float]] = {
    "tech":      (25.0, 10.0),
    "health":    (20.0,  8.0),
    "financial": (25.0, 10.0),
    "consumer":  (10.0,  3.0),
    "energy":    (15.0,  5.0),
    "utility":   (18.0,  8.0),
    "default":   (18.0,  7.0),
}

# ROIC reference bands
_ROIC_BANDS: dict[str, tuple[float, float]] = {
    "tech":      (20.0,  8.0),
    "health":    (15.0,  6.0),
    "financial": (12.0,  5.0),
    "consumer":  (12.0,  5.0),
    "energy":    ( 8.0,  3.0),
    "utility":   ( 7.0,  3.0),
    "default":   (14.0,  6.0),
}


# ---------------------------------------------------------------------------
# Buffett lens — quality moat: high ROIC, wide gross margin, positive FCF,
#                low leverage, and improving trends.
# ---------------------------------------------------------------------------

def score_buffett(metrics: dict[str, Any], sector: Optional[str] = None) -> float:
    sk = _sector_key(sector)
    gm_good, gm_ok = _GROSS_MARGIN_BANDS[sk]
    roic_good, roic_ok = _ROIC_BANDS[sk]

    score = 50.0

    # ROIC: most important signal of durable competitive advantage
    roic = _metric_or_zero(metrics, "roic")
    score += _soft(roic, roic_good, roic_ok, scale=14.0)

    # Gross margin: proxy for pricing power
    gm = _metric_or_zero(metrics, "gross_margin")
    score += _soft(gm, gm_good, gm_ok, scale=10.0)

    # FCF: normalised to revenue so large-cap doesn't dominate small-cap
    rev = _metric_or_zero(metrics, "revenue")
    fcf = _metric_or_zero(metrics, "fcf")
    if rev > 0:
        fcf_margin = fcf / rev * 100.0
        score += _soft(fcf_margin, 15.0, 0.0, scale=10.0)
    elif fcf > 0:
        score += 5.0  # positive FCF with no revenue context
    else:
        score -= 8.0  # negative FCF is a red flag

    # Debt/EBITDA: leverage penalty
    de = _metric_or_zero(metrics, "debt_to_ebitda")
    score += _soft(de, 0.5, 3.5, scale=8.0)   # good=low debt, bad=high debt

    # Trend bonuses (secondary — max ±6 total)
    score += _bounded_contribution(metrics.get("gross_margin_trend"), 0.3, -3.0, 3.0)

    score += _bounded_contribution(metrics.get("fcf_cagr_pct"), 0.1, -3.0, 3.0)

    return _clamp(score)


# ---------------------------------------------------------------------------
# Ackman lens — concentrated quality: high operating margin, strong interest
#               coverage, improving ROIC, expanding margins.
# ---------------------------------------------------------------------------

def score_ackman(metrics: dict[str, Any], sector: Optional[str] = None) -> float:
    sk = _sector_key(sector)
    op_good, op_ok = _OP_MARGIN_BANDS[sk]
    roic_good, roic_ok = _ROIC_BANDS[sk]

    score = 45.0

    # Operating margin: core profitability
    om = _metric_or_zero(metrics, "operating_margin")
    score += _soft(om, op_good, op_ok, scale=14.0)

    # Interest coverage: financial safety
    ic = _metric_or_zero(metrics, "interest_coverage")
    score += _soft(ic, 12.0, 3.0, scale=10.0)

    # ROIC
    roic = _metric_or_zero(metrics, "roic")
    score += _soft(roic, roic_good, roic_ok, scale=8.0)

    # Margin expansion trend (Ackman prizes improving businesses)
    score += _bounded_contribution(metrics.get("operating_margin_trend"), 0.5, -5.0, 5.0)

    return _clamp(score)


# ---------------------------------------------------------------------------
# Wood lens — growth & innovation: revenue growth is primary, gross margin
#             shows scalability, FCF CAGR shows the growth is converting.
#             P/E penalty is removed — Wood explicitly accepts high valuations
#             for disruptive growth.
# ---------------------------------------------------------------------------

def score_wood(metrics: dict[str, Any], sector: Optional[str] = None) -> float:
    score = 35.0

    # Revenue growth: primary signal
    rg = _metric_or_zero(metrics, "revenue_growth_pct")
    score += _soft(rg, 25.0, 5.0, scale=20.0)

    # Gross margin: scalability of the growth
    gm = _metric_or_zero(metrics, "gross_margin")
    score += _soft(gm, 60.0, 30.0, scale=10.0)

    # FCF CAGR: growth converting to cash (secondary)
    score += _bounded_contribution(metrics.get("fcf_cagr_pct"), 0.2, -5.0, 8.0)

    return _clamp(score)


# ---------------------------------------------------------------------------
# Burry lens — deep value / balance sheet: low leverage, strong liquidity,
#              reasonable valuation. Sector-adjusted debt thresholds.
# ---------------------------------------------------------------------------

def score_burry(metrics: dict[str, Any], sector: Optional[str] = None) -> float:
    sk = _sector_key(sector)

    # Debt/EBITDA tolerance differs by sector
    de_good = 0.5 if sk in ("tech", "health") else 1.0
    de_bad  = 3.0 if sk in ("tech", "health") else 4.5

    score = 45.0

    # Current ratio: liquidity buffer
    cr = _metric_or_zero(metrics, "current_ratio")
    score += _soft(cr, 2.5, 0.8, scale=12.0)

    # Debt/EBITDA: leverage (good = low)
    de = _metric_or_zero(metrics, "debt_to_ebitda")
    score += _soft(de, de_good, de_bad, scale=12.0)

    # Interest coverage
    ic = _metric_or_zero(metrics, "interest_coverage")
    score += _soft(ic, 10.0, 2.0, scale=8.0)

    # P/E: Burry looks for undervaluation (good = low P/E)
    pe = _finite_or_none(metrics.get("valuation_pe"))
    if pe is not None and pe > 0:
        score += _soft(pe, 12.0, 30.0, scale=8.0)

    # Deleveraging trend bonus
    score += _bounded_contribution(metrics.get("debt_trend"), -1.0, -4.0, 4.0)

    return _clamp(score)


# ---------------------------------------------------------------------------
# Institutional lens — scale, ROE, and earnings quality.
#                      Uses real revenue as a size proxy instead of
#                      hardcoded market cap.
# ---------------------------------------------------------------------------

def score_institutional(metrics: dict[str, Any], sector: Optional[str] = None) -> float:
    score = 45.0

    # ROE: return on equity (sector-adjusted)
    sk = _sector_key(sector)
    roe_good = 20.0 if sk in ("tech", "health") else 15.0
    roe_ok   = 8.0  if sk in ("tech", "health") else 6.0
    roe = _metric_or_zero(metrics, "roe")
    score += _soft(roe, roe_good, roe_ok, scale=14.0)

    # Revenue scale proxy: $10B+ is large-cap institutional territory
    rev = _metric_or_zero(metrics, "revenue")
    rev_bn = rev / 1e9
    score += _soft(rev_bn, 50.0, 5.0, scale=8.0)

    # Net margin: earnings quality
    nm = _metric_or_zero(metrics, "net_margin")
    score += _soft(nm, 15.0, 3.0, scale=8.0)

    # ROE trend (institutions want improving returns)
    score += _bounded_contribution(metrics.get("roe_trend"), 0.3, -4.0, 4.0)

    return _clamp(score)
