from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class RecommendationOut(BaseModel):
    ticker: str
    status: str
    final_score: float
    summary: str
    horizon: Optional[str] = None
    as_of: datetime


class RecommendationDetailOut(RecommendationOut):
    persona_scores: dict[str, float] = Field(default_factory=dict)
    thesis: dict[str, Any] = Field(default_factory=dict)
    risks: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    filing_years_analyzed: list[int] = Field(default_factory=list)


class GenericMessage(BaseModel):
    message: str
