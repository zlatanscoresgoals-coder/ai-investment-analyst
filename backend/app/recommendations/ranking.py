"""Composite ordering for Meridian leaderboard (financials + stored news risk)."""

from __future__ import annotations

import math
from typing import Optional

from app.config import settings


def composite_leaderboard_score(final_score: float, news_risk: Optional[float]) -> float:
    """Lower headline risk than neutral helps slightly; higher risk penalizes rank."""
    try:
        score = float(final_score)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(score):
        return 0.0

    try:
        nr = float(news_risk) if news_risk is not None else settings.news_risk_neutral
    except (TypeError, ValueError):
        nr = settings.news_risk_neutral
    if not math.isfinite(nr):
        nr = settings.news_risk_neutral

    neutral = settings.news_risk_neutral
    penalty = (nr - neutral) * (settings.news_ranking_weight / 100.0) * 12.0
    return max(0.0, min(100.0, score - penalty))
