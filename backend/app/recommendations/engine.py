from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.analysis.financial_ratios import compute_financial_ratios
from app.config import settings
from app.models import Company, ContextSignal, Filing, FinancialMetric, PersonaScore, Recommendation
from app.recommendations.forward_case import build_forward_investment_case
from app.recommendations.persona_elaboration import build_persona_lens_elaboration
from app.news.investor_news import fetch_investor_news
from app.news.news_risk import headline_news_risk_score
from app.scoring.blender import WEIGHTS, score_all


def run_recommendation_for_company(db: Session, company: Company) -> Recommendation:
    metric_rows = (
        db.query(FinancialMetric)
        .filter(FinancialMetric.company_id == company.id)
        .order_by(FinancialMetric.fiscal_year.desc())
        .limit(3)
        .all()
    )
    if not metric_rows:
        raise ValueError(f"No financial metrics available for {company.ticker}. Fetch filings first.")

    latest = metric_rows[0]
    prior = metric_rows[1] if len(metric_rows) > 1 else None

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
        "market_cap_bn": 250.0,
        "liquidity_score": 70.0,
    }
    prior_metrics = {"revenue": prior.revenue} if prior else None
    metrics = compute_financial_ratios(raw_metrics, prior_metrics=prior_metrics)
    score_card = score_all(metrics)
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

    persona_reasoning = [
        (
            f"Buffett lens ({score_card['buffett_score']:.1f}): "
            f"gross margin {latest.gross_margin or 0:.2f}%, FCF {((latest.fcf or 0)/1_000_000_000):.2f}B."
        ),
        (
            f"Ackman lens ({score_card['ackman_score']:.1f}): "
            f"operating margin {latest.operating_margin or 0:.2f}% with quality bias."
        ),
        (
            f"Wood lens ({score_card['wood_score']:.1f}): "
            f"revenue growth trend {revenue_growth:.2f}% as innovation/growth proxy."
        ),
        (
            f"Burry lens ({score_card['burry_score']:.1f}): "
            f"current ratio {latest.current_ratio or 0:.2f}, debt to EBITDA {latest.debt_to_ebitda or 0:.2f}."
        ),
        (
            f"Institutional lens ({score_card['institutional_score']:.1f}): "
            "liquidity and scale assumptions support portfolio inclusion."
        ),
    ]

    def check(name: str, actual, threshold, comparator: str = ">=") -> dict:
        if actual is None:
            return {"criterion": name, "actual": None, "threshold": threshold, "comparator": comparator, "pass": False}
        passed = actual >= threshold if comparator == ">=" else actual <= threshold
        return {"criterion": name, "actual": actual, "threshold": threshold, "comparator": comparator, "pass": passed}

    persona_checklist = {
        "buffett": [
            check("ROIC proxy", latest.roic, 12.0, ">="),
            check("Gross margin (%)", latest.gross_margin, 35.0, ">="),
            check("Positive FCF", latest.fcf, 0.0, ">="),
            check("Debt/EBITDA", latest.debt_to_ebitda, 2.5, "<="),
        ],
        "ackman": [
            check("Operating margin (%)", latest.operating_margin, 15.0, ">="),
            check("ROIC proxy", latest.roic, 12.0, ">="),
            check("Interest coverage", latest.interest_coverage, 5.0, ">="),
        ],
        "wood": [
            check("Revenue growth (%)", revenue_growth, 8.0, ">="),
            check("Gross margin (%)", latest.gross_margin, 40.0, ">="),
        ],
        "burry": [
            check("Current ratio", latest.current_ratio, 1.2, ">="),
            check("Debt/EBITDA", latest.debt_to_ebitda, 3.0, "<="),
            check("P/E", latest.valuation_pe, 22.0, "<="),
        ],
        "institutional": [
            check("ROE (%)", latest.roe, 12.0, ">="),
            check("Liquidity score", raw_metrics.get("liquidity_score"), 60.0, ">="),
            check("Market cap (bn)", raw_metrics.get("market_cap_bn"), 50.0, ">="),
        ],
    }

    score_contribution = {
        "buffett": score_card["buffett_score"] * WEIGHTS["buffett"],
        "ackman": score_card["ackman_score"] * WEIGHTS["ackman"],
        "wood": score_card["wood_score"] * WEIGHTS["wood"],
        "burry": score_card["burry_score"] * WEIGHTS["burry"],
        "pelosi_proxy": score_card["pelosi_proxy_score"] * WEIGHTS["pelosi_proxy"],
        "institutional": score_card["institutional_score"] * WEIGHTS["institutional"],
    }

    persona_for_top = {
        "buffett_score": "quality / moat (Buffett-style)",
        "ackman_score": "concentrated quality (Ackman-style)",
        "wood_score": "growth & innovation (Wood-style)",
        "burry_score": "value / balance sheet (Burry-style)",
        "pelosi_proxy_score": "disclosure-style signal (weak)",
        "institutional_score": "scale & liquidity (index-style)",
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
                f"Revenue growth trend: {revenue_growth:.2f}%.",
                f"Operating margin: {latest.operating_margin or 0:.2f}%.",
                f"ROE proxy: {latest.roe or 0:.2f}%.",
                f"Analyzed 10-K fiscal years: {filing_years if filing_years else 'unavailable'}",
                "Fits multi-persona style blend.",
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
        risk_json={
            "key_risks": [
                "Macro slowdown",
                "Multiple compression",
                "Changes in filing risk language or litigation intensity",
            ],
            "risk_word_hits": {"risk": keyword_counts["risk"], "litigation": keyword_counts["litigation"]},
        },
        horizon="12-36 months",
    )
    db.add(recommendation)

    persona_row = PersonaScore(company_id=company.id, confidence=0.65, **score_card)
    db.add(persona_row)

    news_rows = fetch_investor_news(company, days=14, limit=15)
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
