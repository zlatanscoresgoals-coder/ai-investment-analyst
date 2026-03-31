from typing import Any


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def score_buffett(metrics: dict[str, Any]) -> float:
    score = 50.0
    score += (metrics.get("roic") or 0) * 0.8
    score += (metrics.get("gross_margin") or 0) * 0.3
    score += (metrics.get("fcf") or 0) / 1_000_000_000
    score -= (metrics.get("debt_to_ebitda") or 0) * 4
    return _clamp(score)


def score_ackman(metrics: dict[str, Any]) -> float:
    score = 45.0
    score += (metrics.get("operating_margin") or 0) * 0.6
    score += (metrics.get("interest_coverage") or 0) * 2.0
    score += (metrics.get("roic") or 0) * 0.5
    return _clamp(score)


def score_wood(metrics: dict[str, Any]) -> float:
    score = 40.0
    score += (metrics.get("revenue_growth_pct") or 0) * 1.0
    score += (metrics.get("gross_margin") or 0) * 0.4
    score -= (metrics.get("valuation_pe") or 0) * 0.15
    return _clamp(score)


def score_burry(metrics: dict[str, Any]) -> float:
    score = 50.0
    score += (metrics.get("current_ratio") or 0) * 8
    score += (metrics.get("interest_coverage") or 0) * 1.2
    score -= (metrics.get("debt_to_ebitda") or 0) * 5
    score -= (metrics.get("valuation_pe") or 0) * 0.2
    return _clamp(score)


def score_pelosi_proxy(_metrics: dict[str, Any]) -> float:
    return 55.0


def score_institutional(metrics: dict[str, Any]) -> float:
    score = 50.0
    score += (metrics.get("market_cap_bn") or 0) * 0.2
    score += (metrics.get("liquidity_score") or 0) * 0.25
    score += (metrics.get("roe") or 0) * 0.4
    return _clamp(score)
