from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.analysis.financial_ratios import compute_financial_ratios
from app.config import settings
from app.ingestion.sec_filings import fetch_financial_metrics_last_3y
from app.models import Company, ContextSignal, Filing, FinancialMetric, PersonaScore, Recommendation
from app.recommendations.forward_case import build_forward_investment_case
from app.recommendations.persona_elaboration import build_persona_lens_elaboration
from app.news.investor_news import fetch_investor_news
from app.news.news_risk import headline_news_risk_score
from app.risk.company_risks import build_company_risk_json
from app.scoring.blender import WEIGHTS, score_all


class _MetricProxy:
    """Lightweight stand-in for FinancialMetric when DB rows are absent."""
    __slots__ = (
        "fiscal_year", "revenue", "gross_margin", "operating_margin", "net_margin",
        "fcf", "roic", "roe", "debt_to_ebitda", "interest_coverage",
        "current_ratio", "valuation_pe", "valuation_ev_ebitda",
    )

    def __init__(self, d: dict):
        for s in self.__slots__:
            setattr(self, s, d.get(s))


def _ensure_metric_rows(db: Session, company: Company) -> list:
    """
    Always re-fetch the latest 3 fiscal years from SEC Company Facts and upsert into DB.
    This ensures that newly filed 10-Ks (e.g. FY2025 filed in early 2026) are picked up
    on every analysis run rather than serving stale cached rows.
    Falls back to existing DB rows only if SEC returns nothing.
    """
    sec_metrics = fetch_financial_metrics_last_3y(company.ticker.upper())

    if sec_metrics:
        for m in sec_metrics:
            fy = m["fiscal_year"]
            existing = (
                db.query(FinancialMetric)
                .filter(
                    FinancialMetric.company_id == company.id,
                    FinancialMetric.fiscal_year == fy,
                )
                .first()
            )
            if existing:
                # Update every field in-place so we pick up restated/amended values.
                for field, val in m.items():
                    if field != "fiscal_year":
                        setattr(existing, field, val)
            else:
                db.add(FinancialMetric(company_id=company.id, **m))
        db.commit()

    rows = (
        db.query(FinancialMetric)
        .filter(FinancialMetric.company_id == company.id)
        .order_by(FinancialMetric.fiscal_year.desc())
        .limit(3)
        .all()
    )
    if not rows:
        raise ValueError(
            f"No financial metrics available for {company.ticker}. "
            "SEC Company Facts returned no annual data."
        )
    return rows


def run_recommendation_for_company(db: Session, company: Company) -> Recommendation:
    metric_rows = _ensure_metric_rows(db, company)

    latest = metric_rows[0]
    prior = metric_rows[1] if len(metric_rows) > 1 else None

    # Build trend_rows first so compute_financial_ratios can derive 3-year signals.
    trend_rows = []
    for row in metric_rows:
        trend_rows.append(
            {
                "fiscal_year": row.fiscal_year,
                "revenue": row.revenue,
                "gross_margin": row.gross_margin,
                "operating_margin": row.operating_margin,
                "net_margin": row.net_margin,
                "fcf": row.fcf,
                "roic": row.roic,
                "roe": row.roe,
                "current_ratio": row.current_ratio,
                "debt_to_ebitda": row.debt_to_ebitda,
                "interest_coverage": row.interest_coverage,
                "valuation_pe": row.valuation_pe,
            }
        )

    sector = getattr(company, "sector", None)

    raw_metrics = {
        "revenue": latest.revenue,
        "gross_margin": latest.gross_margin,
        "operating_margin": latest.operating_margin,
        "net_margin": latest.net_margin,
        "fcf": latest.fcf,
        "roic": latest.roic,
        "roe": latest.roe,
        "debt_to_ebitda": latest.debt_to_ebitda,
        "interest_coverage": latest.interest_coverage,
        "current_ratio": latest.current_ratio,
        "valuation_pe": latest.valuation_pe,
        "valuation_ev_ebitda": latest.valuation_ev_ebitda,
    }
    prior_metrics = {"revenue": prior.revenue} if prior else None
    metrics = compute_financial_ratios(raw_metrics, prior_metrics=prior_metrics, trend_rows=trend_rows)
    score_card = score_all(metrics, sector=sector)
    filings = (
        db.query(Filing)
        .filter(Filing.company_id == company.id, Filing.filing_type == "10-K")
        .order_by(Filing.fiscal_year.desc())
        .limit(3)
        .all()
    )

    status = "recommended" if score_card["final_score"] >= settings.recommendation_threshold else "watchlist"
    prev_rec = (
        db.query(Recommendation)
        .filter(Recommendation.company_id == company.id)
        .order_by(Recommendation.as_of.desc())
        .first()
    )
    now_utc = datetime.now(timezone.utc)
    prev_as_of = None
    if prev_rec and prev_rec.as_of:
        pa = prev_rec.as_of
        prev_as_of = pa if pa.tzinfo else pa.replace(tzinfo=timezone.utc)
    if (
        prev_rec
        and prev_rec.status == "recommended"
        and score_card["final_score"] >= (settings.recommendation_threshold - settings.recommendation_hysteresis_buffer)
        and prev_as_of is not None
        and prev_as_of >= (now_utc - timedelta(minutes=settings.recommendation_hysteresis_minutes))
    ):
        # Prevent recommendation churn from short-term noise.
        status = "recommended"
    revenue_growth = metrics.get("revenue_growth_pct") or 0.0
    filing_years = [f.fiscal_year for f in filings]

    keyword_counts = {"risk": 0, "ai": 0, "debt": 0, "litigation": 0, "growth": 0}
    for filing in filings:
        text = (filing.raw_text or "").lower()
        if not text:
            continue
        for key in keyword_counts:
            keyword_counts[key] += text.count(key)

    # Sector-relative checklist thresholds
    _sk = (sector or "").lower()
    _is_tech = any(k in _sk for k in ("tech", "software", "semiconductor", "internet", "cloud"))
    _is_fin  = any(k in _sk for k in ("bank", "financ", "insur", "credit"))
    _is_energy = any(k in _sk for k in ("energy", "oil", "gas", "mining"))

    _roic_bar   = 15.0 if _is_tech else (8.0 if _is_energy else 12.0)
    _gm_bar     = 50.0 if _is_tech else (30.0 if _is_fin else 35.0)
    _om_bar     = 20.0 if _is_tech else (10.0 if _is_energy else 15.0)
    _de_bar     = 2.0  if _is_tech else (4.0  if _is_fin   else 2.5)
    _roe_bar    = 18.0 if _is_tech else (10.0 if _is_energy else 12.0)
    _rev_bn_bar = (latest.revenue or 0) / 1e9  # use actual revenue as the scale check

    fcf_margin = (
        (latest.fcf / latest.revenue * 100.0)
        if (latest.fcf is not None and latest.revenue and latest.revenue > 0)
        else None
    )
    om_trend = metrics.get("operating_margin_trend")
    fcf_cagr = metrics.get("fcf_cagr_pct")

    persona_reasoning = [
        (
            f"Buffett lens ({score_card['buffett_score']:.1f}): "
            f"ROIC {latest.roic or 0:.1f}% (bar {_roic_bar:.0f}%), "
            f"gross margin {latest.gross_margin or 0:.1f}%, "
            f"FCF margin {fcf_margin:.1f}% of revenue." if fcf_margin is not None
            else f"Buffett lens ({score_card['buffett_score']:.1f}): "
            f"ROIC {latest.roic or 0:.1f}%, gross margin {latest.gross_margin or 0:.1f}%."
        ),
        (
            f"Ackman lens ({score_card['ackman_score']:.1f}): "
            f"operating margin {latest.operating_margin or 0:.1f}% "
            f"({'expanding' if om_trend and om_trend > 0 else 'contracting' if om_trend and om_trend < 0 else 'stable'} "
            f"over 3 years), interest coverage {latest.interest_coverage or 0:.1f}×."
        ),
        (
            f"Wood lens ({score_card['wood_score']:.1f}): "
            f"revenue growth {revenue_growth:.1f}% YoY, "
            f"FCF CAGR {fcf_cagr:.1f}% over 3 years." if fcf_cagr is not None
            else f"Wood lens ({score_card['wood_score']:.1f}): revenue growth {revenue_growth:.1f}% YoY."
        ),
        (
            f"Burry lens ({score_card['burry_score']:.1f}): "
            f"current ratio {latest.current_ratio or 0:.2f}, "
            f"debt/EBITDA {latest.debt_to_ebitda or 0:.2f}× "
            f"(sector bar ≤{_de_bar:.1f}×)."
        ),
        (
            f"Institutional lens ({score_card['institutional_score']:.1f}): "
            f"ROE {latest.roe or 0:.1f}% (bar {_roe_bar:.0f}%), "
            f"revenue ${_rev_bn_bar:.1f}B, net margin {latest.net_margin or 0:.1f}%."
        ),
    ]

    def check(name: str, actual, threshold, comparator: str = ">=") -> dict:
        if actual is None:
            return {"criterion": name, "actual": None, "threshold": threshold, "comparator": comparator, "pass": False}
        passed = actual >= threshold if comparator == ">=" else actual <= threshold
        return {"criterion": name, "actual": actual, "threshold": threshold, "comparator": comparator, "pass": passed}

    persona_checklist = {
        "buffett": [
            check("ROIC (%)", latest.roic, _roic_bar, ">="),
            check("Gross margin (%)", latest.gross_margin, _gm_bar, ">="),
            check("Positive FCF", latest.fcf, 0.0, ">="),
            check("Debt/EBITDA", latest.debt_to_ebitda, _de_bar, "<="),
        ],
        "ackman": [
            check("Operating margin (%)", latest.operating_margin, _om_bar, ">="),
            check("ROIC (%)", latest.roic, _roic_bar, ">="),
            check("Interest coverage", latest.interest_coverage, 5.0, ">="),
        ],
        "wood": [
            check("Revenue growth (%)", revenue_growth, 8.0, ">="),
            check("Gross margin (%)", latest.gross_margin, 40.0, ">="),
            check("FCF CAGR (%)", metrics.get("fcf_cagr_pct"), 10.0, ">="),
        ],
        "burry": [
            check("Current ratio", latest.current_ratio, 1.2, ">="),
            check("Debt/EBITDA", latest.debt_to_ebitda, _de_bar, "<="),
            check("P/E", latest.valuation_pe, 25.0, "<="),
        ],
        "institutional": [
            check("ROE (%)", latest.roe, _roe_bar, ">="),
            check("Revenue scale ($B)", _rev_bn_bar, 10.0, ">="),
            check("Net margin (%)", latest.net_margin, 8.0, ">="),
        ],
    }

    score_contribution = {
        "buffett": score_card["buffett_score"] * WEIGHTS["buffett"],
        "ackman": score_card["ackman_score"] * WEIGHTS["ackman"],
        "wood": score_card["wood_score"] * WEIGHTS["wood"],
        "burry": score_card["burry_score"] * WEIGHTS["burry"],
        "pelosi_proxy": 0.0,
        "institutional": score_card["institutional_score"] * WEIGHTS["institutional"],
    }

    persona_for_top = {
        "buffett_score": "quality / moat (Buffett-style)",
        "ackman_score": "concentrated quality (Ackman-style)",
        "wood_score": "growth & innovation (Wood-style)",
        "burry_score": "value / balance sheet (Burry-style)",
        "pelosi_proxy_score": "n/a",
        "institutional_score": "scale & earnings quality (institutional)",
    }
    score_keys = [k for k in score_card if k.endswith("_score") and k != "final_score"]
    top_key = max(score_keys, key=lambda k: score_card[k]) if score_keys else "buffett_score"
    top_persona_label = persona_for_top.get(top_key, "blended")

    forward_case = build_forward_investment_case(
        company_name=company.name,
        ticker=company.ticker,
        revenue_growth_pct=revenue_growth,
        operating_margin=latest.operating_margin,
        roe=latest.roe,
        fcf=latest.fcf,
        valuation_pe=latest.valuation_pe,
        final_score=score_card["final_score"],
        top_persona=top_persona_label,
    )

    persona_lens_elaboration = build_persona_lens_elaboration(
        score_card=score_card,
        weights=WEIGHTS,
        persona_checklist=persona_checklist,
        latest=latest,
        revenue_growth=revenue_growth,
        trend_rows=trend_rows,
        keyword_counts=keyword_counts,
        raw_metrics=raw_metrics,
    )

    try:
        news_rows = fetch_investor_news(company, days=14, limit=15)
    except Exception:
        news_rows = []

    risk_json = build_company_risk_json(
        company_name=company.name,
        ticker=company.ticker,
        sector=getattr(company, "sector", None),
        latest=latest,
        revenue_growth=revenue_growth,
        trend_rows=trend_rows,
        keyword_counts=keyword_counts,
        news_rows=news_rows,
    )

    recommendation = Recommendation(
        company_id=company.id,
        as_of=datetime.now(timezone.utc),
        status=status,
        final_score=score_card["final_score"],
        summary=(
            "Selected by blended investor framework with filing-first analysis "
            "and secondary context from analysts/news/search trends."
        ),
        thesis_json={
            "why_now": [
                f"Revenue growth: {revenue_growth:.1f}% YoY"
                + (f", FCF CAGR {metrics['fcf_cagr_pct']:.1f}% (3Y)" if metrics.get("fcf_cagr_pct") is not None else "") + ".",
                f"Operating margin: {latest.operating_margin or 0:.1f}%"
                + (f" ({'expanding' if (metrics.get('operating_margin_trend') or 0) > 0 else 'contracting'} trend)" if metrics.get("operating_margin_trend") is not None else "") + ".",
                f"ROE: {latest.roe or 0:.1f}%, ROIC: {latest.roic or 0:.1f}% (sector bar {_roic_bar:.0f}%).",
                f"Analyzed 10-K fiscal years: {filing_years if filing_years else 'unavailable'}",
                "Fits multi-persona style blend with sector-relative thresholds.",
            ],
            "filing_scope": "Last 3 annual 10-K filings via SEC or IR.",
            "key_financials": {
                "revenue": latest.revenue,
                "gross_margin": latest.gross_margin,
                "operating_margin": latest.operating_margin,
                "net_margin": latest.net_margin,
                "fcf": latest.fcf,
                "roic": latest.roic,
                "roe": latest.roe,
                "current_ratio": latest.current_ratio,
                "debt_to_ebitda": latest.debt_to_ebitda,
                "revenue_growth_pct": revenue_growth,
                "fcf_cagr_pct": metrics.get("fcf_cagr_pct"),
                "operating_margin_trend": metrics.get("operating_margin_trend"),
                "roe_trend": metrics.get("roe_trend"),
            },
            "persona_reasoning": persona_reasoning,
            "persona_lens_elaboration": persona_lens_elaboration,
            "persona_checklist": persona_checklist,
            "score_contribution": score_contribution,
            "score_weights": WEIGHTS,
            "three_year_trends": trend_rows,
            "filing_word_search": keyword_counts,
            "external_context_note": "Analyst/news/search signals are secondary and do not override the framework.",
            "hysteresis_rule": {
                "enabled": True,
                "buffer_points": settings.recommendation_hysteresis_buffer,
                "cooldown_minutes": settings.recommendation_hysteresis_minutes,
            },
            "investment_case_forward": forward_case,
        },
        risk_json=risk_json,
        horizon="12-36 months",
    )
    db.add(recommendation)

    persona_row = PersonaScore(company_id=company.id, confidence=0.65, **score_card)
    db.add(persona_row)

    news_risk = headline_news_risk_score(
        news_rows,
        neutral=settings.news_risk_neutral,
    )
    context_row = ContextSignal(
        company_id=company.id,
        analyst_consensus_score=55.0,
        news_risk_score=news_risk,
        search_interest_score=55.0,
        notes_json={
            "headline_count": len(news_rows),
            "source": "analysis_run_headlines",
            "note": "News risk informs ranking; filing-first scores are primary.",
        },
    )
    db.add(context_row)

    db.commit()
    db.refresh(recommendation)
    return recommendation
