from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.db import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(16), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    sector = Column(String(128), nullable=True)
    industry = Column(String(128), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Filing(Base):
    __tablename__ = "filings"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    filing_type = Column(String(16), nullable=False, default="10-K")
    filing_date = Column(Date, nullable=False)
    fiscal_year = Column(Integer, nullable=False, index=True)
    source = Column(String(16), nullable=False, default="sec")
    url = Column(String(1024), nullable=False)
    raw_text = Column(Text, nullable=True)
    parsed_json = Column(JSON, nullable=True)


class FinancialMetric(Base):
    __tablename__ = "financial_metrics"
    __table_args__ = (UniqueConstraint("company_id", "fiscal_year", name="uq_financial_metric_company_fy"),)

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    fiscal_year = Column(Integer, nullable=False, index=True)
    revenue = Column(Float, nullable=True)
    gross_margin = Column(Float, nullable=True)
    operating_margin = Column(Float, nullable=True)
    net_margin = Column(Float, nullable=True)
    fcf = Column(Float, nullable=True)
    roic = Column(Float, nullable=True)
    roe = Column(Float, nullable=True)
    debt_to_ebitda = Column(Float, nullable=True)
    interest_coverage = Column(Float, nullable=True)
    current_ratio = Column(Float, nullable=True)
    shares_outstanding = Column(Float, nullable=True)
    valuation_pe = Column(Float, nullable=True)
    valuation_ev_ebitda = Column(Float, nullable=True)


class PersonaScore(Base):
    __tablename__ = "persona_scores"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    as_of = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    buffett_score = Column(Float, nullable=False)
    ackman_score = Column(Float, nullable=False)
    wood_score = Column(Float, nullable=False)
    burry_score = Column(Float, nullable=False)
    pelosi_proxy_score = Column(Float, nullable=False)
    institutional_score = Column(Float, nullable=False)
    final_score = Column(Float, nullable=False, index=True)
    confidence = Column(Float, nullable=False, default=0.5)


class ContextSignal(Base):
    __tablename__ = "context_signals"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    as_of = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    analyst_consensus_score = Column(Float, nullable=True)
    news_risk_score = Column(Float, nullable=True)
    search_interest_score = Column(Float, nullable=True)
    notes_json = Column(JSON, nullable=True)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    as_of = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    status = Column(String(32), nullable=False, index=True)
    final_score = Column(Float, nullable=False)
    summary = Column(Text, nullable=False)
    thesis_json = Column(JSON, nullable=True)
    risk_json = Column(JSON, nullable=True)
    horizon = Column(String(32), nullable=True)


class ScoreAudit(Base):
    __tablename__ = "score_audit"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    as_of = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    factor = Column(String(128), nullable=False)
    old_value = Column(Float, nullable=True)
    new_value = Column(Float, nullable=True)
    reason = Column(Text, nullable=True)


class CriticalAlert(Base):
    __tablename__ = "critical_alerts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    as_of = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    severity = Column(String(32), nullable=False, default="high")
    source = Column(String(64), nullable=False, default="news")
    headline = Column(String(1024), nullable=False)
    url = Column(String(1024), nullable=True)
    details_json = Column(JSON, nullable=True)
