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
    last_price: Optional[float] = None
    price_currency: Optional[str] = None
    price_change_pct_day: Optional[float] = None
    quote_as_of: Optional[str] = None
    quote_source: Optional[str] = None


class RecommendationDetailOut(RecommendationOut):
    persona_scores: dict[str, float] = Field(default_factory=dict)
    thesis: dict[str, Any] = Field(default_factory=dict)
    risks: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    filing_years_analyzed: list[int] = Field(default_factory=list)
    live_quote: Optional[dict[str, Any]] = None


class GenericMessage(BaseModel):
    message: str
