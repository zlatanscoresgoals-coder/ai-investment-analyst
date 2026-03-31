from datetime import datetime
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.db import SessionLocal
from app.ingestion.ir_fetcher import fetch_ir_filing_fallback_urls
from app.ingestion.sec_filings import fallback_financial_metrics_last_3y, fetch_financial_metrics_last_3y, fetch_last_3y_10k_urls
from app.models import Company, Filing, FinancialMetric
from app.recommendations.engine import run_recommendation_for_company
from app.risk.critical_events import apply_critical_risk_gate

_scheduler: Optional[BackgroundScheduler] = None
_state: dict[str, Any] = {
    "last_run_at": None,
    "last_status": "never",
    "last_message": "",
}


def _run_full_job():
    db = SessionLocal()
    try:
        result = execute_full_pipeline(db)
        _state["last_run_at"] = datetime.utcnow().isoformat()
        _state["last_status"] = "ok"
        _state["last_message"] = result.message
    except Exception as exc:
        _state["last_run_at"] = datetime.utcnow().isoformat()
        _state["last_status"] = "error"
        _state["last_message"] = str(exc)
    finally:
        db.close()


def _sync_universe(db):
    starters = [
        ("AAPL", "Apple Inc."),
        ("MSFT", "Microsoft Corporation"),
        ("GOOGL", "Alphabet Inc."),
        ("AMZN", "Amazon.com, Inc."),
        ("XOM", "Exxon Mobil Corporation"),
        ("CVX", "Chevron Corporation"),
        ("NVDA", "NVIDIA Corporation"),
        ("TSLA", "Tesla, Inc."),
        ("JPM", "JPMorgan Chase & Co."),
        ("BRK-B", "Berkshire Hathaway Inc."),
    ]
    for ticker, name in starters:
        exists = db.query(Company).filter(Company.ticker == ticker).first()
        if not exists:
            db.add(Company(ticker=ticker, name=name))
    db.commit()


def _fetch_filings_and_metrics(db, company):
    filings = fetch_last_3y_10k_urls(company.ticker.upper())
    if not filings:
        filings = fetch_ir_filing_fallback_urls(company.ticker.upper())
    for item in filings:
        exists = (
            db.query(Filing)
            .filter(Filing.company_id == company.id, Filing.fiscal_year == item["fiscal_year"], Filing.filing_type == "10-K")
            .first()
        )
        if exists:
            continue
        db.add(
            Filing(
                company_id=company.id,
                filing_type=item["filing_type"],
                filing_date=item["filing_date"],
                fiscal_year=item["fiscal_year"],
                source=item["source"],
                url=item["url"],
                raw_text=item.get("raw_text"),
            )
        )
    metrics = fetch_financial_metrics_last_3y(company.ticker.upper())
    if not metrics:
        metrics = fallback_financial_metrics_last_3y(company.ticker.upper())
    for metric in metrics:
        exists = (
            db.query(FinancialMetric)
            .filter(FinancialMetric.company_id == company.id, FinancialMetric.fiscal_year == metric["fiscal_year"])
            .first()
        )
        if exists:
            for key, value in metric.items():
                setattr(exists, key, value)
        else:
            db.add(FinancialMetric(company_id=company.id, **metric))
    db.commit()


def execute_full_pipeline(db):
    _sync_universe(db)
    companies = db.query(Company).all()
    analyzed = 0
    failures: list[str] = []
    for company in companies:
        try:
            _fetch_filings_and_metrics(db, company)
            run_recommendation_for_company(db, company)
            apply_critical_risk_gate(db, company)
            analyzed += 1
        except Exception as exc:
            failures.append(f"{company.ticker}: {str(exc)}")
            continue
    failure_note = f" Failed: {len(failures)}." if failures else ""
    failure_preview = f" Examples -> {' | '.join(failures[:2])}" if failures else ""
    class Result:
        def __init__(self, message):
            self.message = message
    return Result(f"Full pipeline run finished. Successfully analyzed {analyzed} companies.{failure_note}{failure_preview}")


def start_scheduler():
    global _scheduler
    if not settings.auto_refresh_enabled:
        return
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(_run_full_job, "interval", minutes=settings.auto_refresh_interval_minutes, id="auto_refresh_full")
    _scheduler.start()


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def run_periodic_jobs() -> dict:
    return {
        "auto_refresh_enabled": settings.auto_refresh_enabled,
        "auto_refresh_interval_minutes": settings.auto_refresh_interval_minutes,
        "last_run_at": _state["last_run_at"],
        "last_status": _state["last_status"],
        "last_message": _state["last_message"],
    }
