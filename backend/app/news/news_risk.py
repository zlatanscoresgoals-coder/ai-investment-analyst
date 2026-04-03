"""Headline-based risk score for ranking (stored on ContextSignal at analysis time)."""

from __future__ import annotations

from typing import Any

# Higher score = more headline risk (penalizes composite rank).
_NEGATIVE_HINTS = (
    "lawsuit",
    "investigation",
    "sec charges",
    "subpoena",
    "layoff",
    "layoffs",
    "warning",
    "guidance cut",
    "misses estimates",
    "fraud",
    "breach",
    "downgrade",
    "bankruptcy",
    "probe",
    "settlement",
    "strike",
    "recall",
)


def headline_news_risk_score(headlines: list[dict[str, Any]], *, neutral: float = 32.0) -> float:
    """
    Map recent headline rows (title + description) to 15–92. No external NLP API.
    """
    if not headlines:
        return max(15.0, neutral - 4.0)

    blob = " ".join(
        ((h.get("title") or "") + " " + (h.get("description") or "")).lower() for h in headlines
    )
    neg_hits = sum(1 for w in _NEGATIVE_HINTS if w in blob)
    volume = min(len(headlines), 20)
    # More articles slightly raises baseline attention; negative words push risk up.
    raw = neutral + volume * 1.1 + neg_hits * 9.0
    return float(min(92.0, max(15.0, raw)))
