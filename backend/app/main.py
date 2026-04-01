from datetime import datetime
from pathlib import Path
import secrets
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, SessionLocal, engine, get_db
from app.ingestion.ir_fetcher import fetch_ir_filing_fallback_urls
from app.ingestion.sec_filings import (
    fallback_financial_metrics_last_3y,
    fetch_financial_metrics_last_3y,
    fetch_last_3y_10k_urls,
)
from app.market.quotes import fetch_live_quote, quote_debug_status
from app.models import Company, ContextSignal, CriticalAlert, Filing, FinancialMetric, PersonaScore, Recommendation
from app.news.investor_news import fetch_investor_news
from app.recommendations.engine import run_recommendation_for_company
from app.risk.critical_events import is_actionable_critical_alert
from app.schemas import GenericMessage, InvestorNewsItem, RecommendationDetailOut, RecommendationOut
from app.tasks.scheduler import execute_full_pipeline, run_periodic_jobs, start_scheduler, stop_scheduler

app = FastAPI(title="AI Investment Analyst API", version="0.1.0")
Base.metadata.create_all(bind=engine)
_active_sessions: set[str] = set()
_dashboard_html_cache: Optional[str] = None


def _load_dashboard_html(last_run_display: str) -> str:
    global _dashboard_html_cache
    if _dashboard_html_cache is None:
        path = Path(__file__).resolve().parent / "meridian_dashboard.html"
        _dashboard_html_cache = path.read_text(encoding="utf-8")
    return _dashboard_html_cache.replace("__LAST_RUN__", last_run_display)


def _is_auth_path(path: str) -> bool:
    open_paths = {"/login", "/logout"}
    if path in open_paths:
        return True
    # Liveness / quote diagnostics (no secrets; helps verify Railway env keys and outbound HTTP).
    if path.startswith("/health/"):
        return True
    if path.startswith("/docs") or path.startswith("/openapi") or path.startswith("/redoc"):
        return False
    return False


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not settings.auth_enabled:
        return await call_next(request)

    path = request.url.path
    if _is_auth_path(path):
        return await call_next(request)

    token = request.cookies.get(settings.auth_session_cookie, "")
    if token in _active_sessions:
        return await call_next(request)

    # Browser paths redirect to login; API paths return 401.
    if path == "/" or path == "/dashboard" or request.method == "GET":
        return RedirectResponse(url="/login", status_code=303)
    raise HTTPException(status_code=401, detail="Authentication required.")


@app.on_event("startup")
def on_startup():
    db = SessionLocal()
    try:
        db.query(Recommendation).filter(Recommendation.status == "blocked").update(
            {"status": "watchlist"},
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
    start_scheduler()


@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()


@app.get("/")
def root():
    """
    Never return JSON here — browsers opening the bare service URL should land in the UI.
    (302 + HTML fallback for odd clients.) API health: GET /health/freshness
    """
    return HTMLResponse(
        """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta http-equiv="refresh" content="0;url=/dashboard" />
  <title>MERIDIAN</title>
  <script>location.replace("/dashboard");</script>
</head>
<body style="margin:0;background:#07090D;color:#B4BBC8;font-family:system-ui,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;">
  <p>Opening <a href="/dashboard" style="color:#C9A84C">dashboard</a>…</p>
</body>
</html>"""
    )


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return HTMLResponse(
        """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Sign in | MERIDIAN</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600;700&family=Playfair+Display:wght@600&display=swap" rel="stylesheet" />
  <style>
    body {
      margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
      background:#07090D; color:#F2EDE4; font-family:"DM Sans",system-ui,sans-serif;
    }
    .card {
      width:360px; padding:28px; border-radius:10px;
      background:#0C1118; border:1px solid rgba(255,255,255,0.08);
    }
    .brand { font-family:"Playfair Display",Georgia,serif; font-size:20px; letter-spacing:0.25em; color:#C9A84C; margin:0; }
    .sub { font-size:9px; text-transform:uppercase; letter-spacing:0.2em; color:#8E97A8; margin:6px 0 20px; }
    label { font-size:10px; text-transform:uppercase; letter-spacing:0.15em; color:#B4BBC8; }
    input {
      width:100%; box-sizing:border-box; margin-top:6px; margin-bottom:14px; padding:12px;
      border-radius:8px; border:1px solid rgba(255,255,255,0.1); background:rgba(0,0,0,0.25); color:#F2EDE4;
    }
    button {
      width:100%; padding:12px; border:none; border-radius:8px; cursor:pointer; font-weight:700;
      background:#C9A84C; color:#07090D; font-family:"DM Sans",sans-serif;
    }
    button:hover { filter:brightness(1.06); }
  </style>
</head>
<body>
  <form class="card" method="post" action="/login">
    <h1 class="brand">MERIDIAN</h1>
    <div class="sub">AI Investment Intelligence</div>
    <label for="u">Username</label>
    <input id="u" name="username" autocomplete="username" required />
    <label for="p">Password</label>
    <input id="p" name="password" type="password" autocomplete="current-password" required />
    <button type="submit">Sign in</button>
  </form>
</body>
</html>
        """
    )


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    if username != settings.auth_username or password != settings.auth_password:
        return HTMLResponse("<h3>Invalid credentials. Go back and try again.</h3>", status_code=401)
    token = secrets.token_urlsafe(24)
    _active_sessions.add(token)
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        settings.auth_session_cookie,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 24,
    )
    return response


@app.get("/logout")
def logout(request: Request):
    token = request.cookies.get(settings.auth_session_cookie, "")
    if token in _active_sessions:
        _active_sessions.remove(token)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(settings.auth_session_cookie)
    return response


@app.post("/universe/sync", response_model=GenericMessage)
def sync_universe(db: Session = Depends(get_db)) -> GenericMessage:
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
    return GenericMessage(message="Universe synced with starter tickers.")


@app.post("/filings/fetch/{ticker}", response_model=GenericMessage)
def fetch_filings(ticker: str, db: Session = Depends(get_db)) -> GenericMessage:
    company = db.query(Company).filter(Company.ticker == ticker.upper()).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found in universe.")

    try:
        filings = fetch_last_3y_10k_urls(ticker.upper())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch SEC filings: {exc}") from exc
    if not filings:
        filings = fetch_ir_filing_fallback_urls(ticker.upper())

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

    metrics = fetch_financial_metrics_last_3y(ticker.upper())
    used_fallback = False
    if not metrics:
        metrics = fallback_financial_metrics_last_3y(ticker.upper())
        used_fallback = bool(metrics)
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
    return GenericMessage(
        message=(
            f"Fetched filings and metrics for {ticker.upper()} "
            f"(filings: {len(filings)}, metric years: {len(metrics)}"
            f"{', fallback metrics used' if used_fallback else ''})."
        )
    )


@app.post("/analysis/run/{ticker}", response_model=GenericMessage)
def run_analysis(ticker: str, db: Session = Depends(get_db)) -> GenericMessage:
    company = db.query(Company).filter(Company.ticker == ticker.upper()).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found in universe.")

    try:
        run_recommendation_for_company(db, company)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GenericMessage(message=f"Analysis and scoring completed for {ticker.upper()}.")


@app.post("/recommendations/run", response_model=GenericMessage)
def run_recommendations(db: Session = Depends(get_db)) -> GenericMessage:
    companies = db.query(Company).all()
    if not companies:
        raise HTTPException(status_code=400, detail="Universe is empty. Call /universe/sync first.")

    for company in companies:
        try:
            run_recommendation_for_company(db, company)
        except ValueError:
            continue
    return GenericMessage(message=f"Recommendations generated for {len(companies)} companies.")


@app.post("/run/full", response_model=GenericMessage)
def run_full_pipeline(db: Session = Depends(get_db)) -> GenericMessage:
    result = execute_full_pipeline(db)
    return GenericMessage(
        message=result["message"],
        analyzed=result["analyzed"],
        company_count=result["company_count"],
        failures=result["failures"] or None,
    )


@app.get("/recommendations", response_model=list[RecommendationOut])
def list_recommendations(status: str = Query(default="recommended"), db: Session = Depends(get_db)):
    latest_per_company = (
        db.query(
            Recommendation.company_id.label("company_id"),
            func.max(Recommendation.as_of).label("latest_as_of"),
        )
        .group_by(Recommendation.company_id)
        .subquery()
    )

    rows = (
        db.query(Recommendation, Company)
        .join(Company, Company.id == Recommendation.company_id)
        .join(
            latest_per_company,
            (latest_per_company.c.company_id == Recommendation.company_id)
            & (latest_per_company.c.latest_as_of == Recommendation.as_of),
        )
        .filter(Recommendation.status == status)
        .order_by(Recommendation.final_score.desc())
        .all()
    )
    out: list[RecommendationOut] = []
    for rec, company in rows:
        q = fetch_live_quote(company.ticker)
        out.append(
            RecommendationOut(
                ticker=company.ticker,
                status=rec.status,
                final_score=rec.final_score,
                summary=rec.summary,
                horizon=rec.horizon,
                as_of=rec.as_of,
                last_price=q["last_price"] if q else None,
                price_currency=q.get("currency") if q else None,
                price_change_pct_day=q.get("change_pct_day") if q else None,
                quote_as_of=q.get("as_of") if q else None,
                quote_source=q.get("source") if q else None,
            )
        )
    return out


@app.get("/recommendations/{ticker}", response_model=RecommendationDetailOut)
def get_recommendation_detail(ticker: str, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.ticker == ticker.upper()).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found.")

    rec = (
        db.query(Recommendation)
        .filter(Recommendation.company_id == company.id)
        .order_by(Recommendation.as_of.desc())
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail=f"No recommendation found for {ticker.upper()}.")

    persona = (
        db.query(PersonaScore)
        .filter(PersonaScore.company_id == company.id)
        .order_by(PersonaScore.as_of.desc())
        .first()
    )
    context = (
        db.query(ContextSignal)
        .filter(ContextSignal.company_id == company.id)
        .order_by(ContextSignal.as_of.desc())
        .first()
    )
    filing_years = [f.fiscal_year for f in db.query(Filing).filter(Filing.company_id == company.id).all()]
    live_q = fetch_live_quote(company.ticker)
    news_rows = fetch_investor_news(company)

    return RecommendationDetailOut(
        ticker=company.ticker,
        company_name=company.name,
        sector=company.sector,
        industry=company.industry,
        status=rec.status,
        final_score=rec.final_score,
        summary=rec.summary,
        horizon=rec.horizon,
        as_of=rec.as_of,
        last_price=live_q["last_price"] if live_q else None,
        price_currency=live_q.get("currency") if live_q else None,
        price_change_pct_day=live_q.get("change_pct_day") if live_q else None,
        quote_as_of=live_q.get("as_of") if live_q else None,
        quote_source=live_q.get("source") if live_q else None,
        persona_scores={
            "buffett": persona.buffett_score if persona else 0.0,
            "ackman": persona.ackman_score if persona else 0.0,
            "wood": persona.wood_score if persona else 0.0,
            "burry": persona.burry_score if persona else 0.0,
            "pelosi_proxy": persona.pelosi_proxy_score if persona else 0.0,
            "institutional": persona.institutional_score if persona else 0.0,
        },
        thesis=rec.thesis_json or {},
        risks=rec.risk_json or {},
        context={
            "analyst_consensus_score": context.analyst_consensus_score if context else None,
            "news_risk_score": context.news_risk_score if context else None,
            "search_interest_score": context.search_interest_score if context else None,
            "notes": context.notes_json if context else {},
        },
        filing_years_analyzed=sorted(set(filing_years), reverse=True),
        live_quote=live_q,
        investor_news=[InvestorNewsItem(**n) for n in news_rows],
    )


@app.get("/health/freshness")
def health_freshness():
    return {"status": "ok", "schedules": run_periodic_jobs()}


@app.get("/health/quote")
def health_quote(ticker: str = Query(default="AAPL")):
    """
    Shows which quote providers are configured and which first succeeds for `ticker`.
    Open without login so you can verify FINNHUB_API_KEY etc. on Railway.
    """
    return quote_debug_status(ticker)


@app.get("/health/features")
def health_features():
    """
    Confirms product behavior on the running deploy (no secrets).
    Use this after Railway/Git push to verify you are on the build that includes investor news and no auto-block gate.
    """
    return {
        "auto_block_critical_risk_gate": False,
        "investor_news_on_recommendation_detail": True,
        "startup_migrate_blocked_to_watchlist": True,
        "newsapi_configured": bool((settings.newsapi_key or "").strip()),
        "trusted_outlet_filter_strict": settings.critical_news_strict_outlets,
        "verify_detail_news": "GET /recommendations/AAPL → JSON key investor_news",
        "verify_dashboard": "/dashboard merges recommended + watchlist and loads news per card",
    }


@app.get("/alerts/critical")
def list_critical_alerts(
    limit: int = Query(default=25, ge=1, le=200),
    include_cleared: bool = Query(
        default=False,
        description="If true, include alerts moved to unblocked.",
    ),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(CriticalAlert, Company)
        .join(Company, Company.id == CriticalAlert.company_id)
        .order_by(CriticalAlert.as_of.desc())
        .limit(limit * 3 if not include_cleared else limit)
        .all()
    )
    out: list[dict] = []
    for alert, company in rows:
        ws = (alert.details_json or {}).get("workflow_status", "blocked")
        if not include_cleared and ws == "unblocked":
            continue
        if not include_cleared and ws == "blocked" and not is_actionable_critical_alert(alert):
            continue
        out.append(
            {
                "ticker": company.ticker,
                "company_name": company.name,
                "as_of": alert.as_of,
                "event_type": alert.event_type,
                "severity": alert.severity,
                "source": alert.source,
                "headline": alert.headline,
                "url": alert.url,
                "confidence": (alert.details_json or {}).get("confidence", "unknown"),
                "workflow_status": ws,
            }
        )
        if len(out) >= limit:
            break
    return out


@app.get("/portfolio/impact")
def portfolio_impact(db: Session = Depends(get_db)):
    blocked_rows = (
        db.query(Recommendation, Company)
        .join(Company, Company.id == Recommendation.company_id)
        .filter(Recommendation.status == "blocked")
        .order_by(Recommendation.as_of.desc())
        .all()
    )
    blocked_latest = {}
    for rec, company in blocked_rows:
        if company.ticker not in blocked_latest:
            blocked_latest[company.ticker] = {"ticker": company.ticker, "score": rec.final_score, "as_of": rec.as_of}

    return {
        "blocked_count": len(blocked_latest),
        "avg_blocked_score": (
            sum(v["score"] for v in blocked_latest.values()) / len(blocked_latest) if blocked_latest else None
        ),
        "blocked_tickers": sorted(blocked_latest.keys()),
        "note": "Legacy field: scheduler no longer sets blocked; app startup rewrites existing blocked rows to watchlist.",
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)):
    last_run = db.query(Recommendation).order_by(Recommendation.as_of.desc()).first()
    if last_run and last_run.as_of:
        dt = last_run.as_of
        try:
            last_run_display = f"{dt.strftime('%B')} {dt.day}, {dt.year}"
        except Exception:
            last_run_display = str(last_run.as_of)
    else:
        last_run_display = "Never"
    return HTMLResponse(_load_dashboard_html(last_run_display))
