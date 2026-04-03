from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class InvestorNewsItem(BaseModel):
    title: str
    url: str
    source_name: Optional[str] = None
    published_at: Optional[str] = None
    description: Optional[str] = None


class RecommendationOut(BaseModel):
    ticker: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
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


class LeaderboardItemOut(RecommendationOut):
    """Top names in the screening pool ordered by financial score adjusted for headline risk."""

    composite_score: float
    rank: int


class RecommendationDetailOut(RecommendationOut):
    company_name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    valuation: Optional[dict[str, Any]] = None
    persona_scores: dict[str, float] = Field(default_factory=dict)
    # Duplicated from thesis.key_financials for dashboards (always merged from DB + SEC companyfacts).
    key_financials: dict[str, Any] = Field(default_factory=dict)
    thesis: dict[str, Any] = Field(default_factory=dict)
    risks: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    filing_years_analyzed: list[int] = Field(default_factory=list)
    live_quote: Optional[dict[str, Any]] = None
    investor_news: list[InvestorNewsItem] = Field(default_factory=list)


class GenericMessage(BaseModel):
    message: str
    analyzed: Optional[int] = None
    company_count: Optional[int] = None
    failures: Optional[list[str]] = None


class SecFilingRow(BaseModel):
    fiscal_year: int
    filing_type: str
    filing_date: Optional[date] = None
    url: str
    source: str = "sec"


class SecMetricRow(BaseModel):
    fiscal_year: int
    revenue: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    fcf: Optional[float] = None
    roe: Optional[float] = None
    roic: Optional[float] = None
    current_ratio: Optional[float] = None
    debt_to_ebitda: Optional[float] = None
    interest_coverage: Optional[float] = None
    valuation_pe: Optional[float] = None
    valuation_ev_ebitda: Optional[float] = None


class PortfolioAddIn(BaseModel):
    ticker: str
    entryPrice: float = Field(gt=0)
    shares: float = Field(gt=0)
    entryDate: str
    notes: str = ""


class SecIngestOut(BaseModel):
    ticker: str
    company_name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    filings: list[SecFilingRow] = Field(default_factory=list)
    metrics: list[SecMetricRow] = Field(default_factory=list)
    sec_edgar_search_url: str
    used_fallback_metrics: bool = False
    message: str
