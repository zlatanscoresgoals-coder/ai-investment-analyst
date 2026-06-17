from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Company, FinancialMetric


_SYNTHETIC_FALLBACK_REVENUE_BN: dict[str, list[float]] = {
    "AAPL": [383.3, 394.3, 365.8],
    "MSFT": [245.1, 211.9, 198.3],
    "GOOGL": [307.4, 282.8, 257.6],
    "AMZN": [574.8, 513.9, 469.8],
    "NVDA": [60.9, 26.9, 27.0],
    "TSLA": [96.8, 81.5, 53.8],
    "XOM": [344.6, 413.7, 285.6],
    "CVX": [200.9, 246.3, 162.5],
    "JPM": [158.1, 132.3, 121.6],
    "BRK-B": [364.5, 302.1, 276.1],
}


def _close(actual: float | None, expected: float) -> bool:
    if actual is None:
        return False
    tolerance = max(1e-6, abs(expected) * 1e-12)
    return abs(float(actual) - expected) <= tolerance


def _synthetic_metric_signatures(ticker: str) -> list[dict[str, float]]:
    signatures: list[dict[str, float]] = []
    for i, rev_bn in enumerate(_SYNTHETIC_FALLBACK_REVENUE_BN.get(ticker.upper(), [])):
        revenue = rev_bn * 1_000_000_000.0
        signatures.append(
            {
                "revenue": revenue,
                "gross_margin": 42.0 - i,
                "operating_margin": 25.0 - (i * 0.8),
                "net_margin": 21.0 - (i * 0.7),
                "fcf": revenue * 0.18,
                "roic": 18.0 - (i * 0.4),
                "roe": 20.0 - (i * 0.5),
                "debt_to_ebitda": 1.4 + (i * 0.1),
                "interest_coverage": 9.0 - (i * 0.2),
                "current_ratio": 1.6 - (i * 0.05),
                "valuation_pe": 24.0,
                "valuation_ev_ebitda": 14.0,
            }
        )
    return signatures


def _matches_synthetic_fallback(metric: FinancialMetric, ticker: str) -> bool:
    for signature in _synthetic_metric_signatures(ticker):
        if all(_close(getattr(metric, field), expected) for field, expected in signature.items()):
            return True
    return False


def purge_synthetic_fallback_financial_metrics(db: Session) -> int:
    """Delete only rows matching the complete legacy demo fallback signature."""
    rows = (
        db.query(FinancialMetric, Company.ticker)
        .join(Company, Company.id == FinancialMetric.company_id)
        .filter(
            Company.ticker.in_(list(_SYNTHETIC_FALLBACK_REVENUE_BN.keys())),
            FinancialMetric.operating_margin.in_([25.0, 24.2, 23.4]),
        )
        .all()
    )

    deleted = 0
    for metric, ticker in rows:
        if _matches_synthetic_fallback(metric, ticker):
            db.delete(metric)
            deleted += 1
    return deleted
