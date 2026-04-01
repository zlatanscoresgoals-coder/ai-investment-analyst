from datetime import datetime
import secrets

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
from app.models import Company, ContextSignal, Filing, FinancialMetric, PersonaScore, Recommendation
from app.news.investor_news import fetch_investor_news
from app.recommendations.engine import run_recommendation_for_company
from app.schemas import GenericMessage, InvestorNewsItem, RecommendationDetailOut, RecommendationOut
from app.tasks.scheduler import execute_full_pipeline, run_periodic_jobs, start_scheduler, stop_scheduler

app = FastAPI(title="AI Investment Analyst API", version="0.1.0")
Base.metadata.create_all(bind=engine)
_active_sessions: set[str] = set()


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


@app.get("/", response_model=GenericMessage)
def root() -> GenericMessage:
    return GenericMessage(message="AI Investment Analyst backend is running. Open /dashboard for UI.")


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return HTMLResponse(
        """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Login | AI Investment Analyst</title>
  <style>
    body { background:#0b1220; color:#e6edf7; font-family:Arial,sans-serif; display:flex; justify-content:center; align-items:center; min-height:100vh; margin:0; }
    .card { width:340px; background:#111a2e; border:1px solid #24324e; border-radius:12px; padding:18px; }
    h2 { margin-top:0; }
    input { width:100%; margin-top:8px; margin-bottom:12px; padding:10px; border-radius:8px; border:1px solid #24324e; background:#18233b; color:#e6edf7; }
    button { width:100%; padding:10px; border:none; border-radius:8px; background:#2d7df6; color:white; font-weight:700; cursor:pointer; }
    .err { color:#ef4444; font-size:13px; min-height:18px; }
  </style>
</head>
<body>
  <form class="card" method="post" action="/login">
    <h2>AI Investment Analyst</h2>
    <div>Sign in</div>
    <input name="username" placeholder="Username" required />
    <input name="password" type="password" placeholder="Password" required />
    <button type="submit">Login</button>
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
    last_run_display = last_run.as_of.isoformat() if last_run else "Never"
    return HTMLResponse(
        f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Investment Analyst Dashboard</title>
  <style>
    :root {{
      --bg: #0b1220;
      --panel: #111a2e;
      --panel-2: #18233b;
      --text: #e6edf7;
      --muted: #9fb0cc;
      --border: #24324e;
      --good: #22c55e;
      --bad: #ef4444;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, Arial, sans-serif;
      background: linear-gradient(180deg, #0b1220 0%, #0a0f1d 100%);
      color: var(--text);
    }}
    .wrap {{ max-width: 1260px; margin: 0 auto; padding: 24px; }}
    .topbar {{
      display: flex; justify-content: space-between; align-items: center;
      gap: 12px; margin-bottom: 16px;
      background: rgba(17, 26, 46, 0.8); border: 1px solid var(--border);
      border-radius: 14px; padding: 14px 16px;
    }}
    h1 {{ margin: 0; font-size: 22px; }}
    .subtle {{ color: var(--muted); font-size: 13px; }}
    .actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    button {{
      padding: 10px 14px; border-radius: 10px; border: 1px solid var(--border);
      background: var(--panel-2); color: var(--text); cursor: pointer; font-weight: 600;
    }}
    button.primary {{ background: linear-gradient(90deg, #2d7df6, #4da3ff); border: none; color: #fff; }}
    #status {{
      margin: 14px 0 18px 0; padding: 12px 14px; border-radius: 12px;
      background: var(--panel); border: 1px solid var(--border); color: var(--muted);
      white-space: pre-wrap; font-size: 13px;
    }}
    #recs {{ display: grid; grid-template-columns: 1fr; gap: 14px; }}
    .card {{
      background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 16px;
      box-shadow: 0 6px 28px rgba(0,0,0,0.25);
    }}
    .header {{ display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; }}
    .ticker {{ font-size: 20px; font-weight: 700; }}
    .score {{ font-size: 26px; font-weight: 800; color: #90caf9; }}
    .meta {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; margin-top: 12px; }}
    .panel {{
      background: rgba(24,35,59,0.6); border: 1px solid var(--border); border-radius: 10px; padding: 12px;
    }}
    .panel h3 {{ margin: 0 0 8px 0; font-size: 14px; color: #dbe7ff; }}
    ul {{ margin: 8px 0 0 18px; padding: 0; }}
    li {{ margin: 5px 0; color: #d5def0; font-size: 13px; }}
    .badge {{
      display: inline-block; padding: 3px 8px; border-radius: 999px; font-size: 11px;
      border: 1px solid var(--border); color: var(--muted);
    }}
    .pass {{ color: var(--good); }}
    .fail {{ color: var(--bad); }}
    .kpi {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }}
    .kpi .chip {{ background: #15233c; border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px; font-size: 12px; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    @media (max-width: 900px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <div>
        <h1>AI Investment Analyst</h1>
        <div class="subtle">Institutional-style research dashboard | Last run: <span id="lastRun">{last_run_display}</span></div>
      </div>
      <div class="actions">
        <button class="primary" onclick="runFull()">Run Full Analysis</button>
        <button onclick="loadRecs()">Refresh</button>
        <button onclick="window.location='/logout'">Logout</button>
      </div>
    </div>
    <div id="status">Status: idle</div>
    <div id="recs"></div>
  </div>
<script>
async function runFull() {{
  document.getElementById('status').textContent = "Status: running full pipeline...";
  const res = await fetch('/run/full', {{ method: 'POST' }});
  const data = await res.json();
  let line = "Status: " + data.message;
  if (data.failures && data.failures.length) {{
    line += "\\n\\nPer-ticker errors (see Railway logs for full trace):\\n" + data.failures.slice(0, 8).join("\\n");
  }}
  document.getElementById('status').textContent = line;
  await loadRecs();
}}
async function loadRecs() {{
  const [recRes, watchRes] = await Promise.all([
    fetch('/recommendations?status=recommended'),
    fetch('/recommendations?status=watchlist'),
  ]);
  const recommended = await recRes.json();
  const watchlist = await watchRes.json();
  const byTicker = new Map();
  for (const r of [...recommended, ...watchlist]) {{
    const cur = byTicker.get(r.ticker);
    if (!cur) {{
      byTicker.set(r.ticker, r);
      continue;
    }}
    if (cur.status !== 'recommended' && r.status === 'recommended') {{
      byTicker.set(r.ticker, r);
    }} else if (Number(r.final_score) > Number(cur.final_score)) {{
      byTicker.set(r.ticker, r);
    }}
  }}
  const data = Array.from(byTicker.values()).sort((a, b) => Number(b.final_score) - Number(a.final_score));
  const target = document.getElementById('recs');
  if (!data.length) {{
    target.innerHTML = '<div class="card">No recommendations or watchlist rows yet. Click "Run Full Analysis".</div>';
    return;
  }}
  const detailed = await Promise.all(data.map(async (r) => {{
    const dr = await fetch(`/recommendations/${{r.ticker}}`);
    const detail = await dr.json();
    return {{ ...r, detail }};
  }}));
  target.innerHTML = detailed.map(item => {{
    const d = item.detail || {{}};
    const whyNow = (d.thesis && d.thesis.why_now) ? d.thesis.why_now : [];
    const personaReasoning = (d.thesis && d.thesis.persona_reasoning) ? d.thesis.persona_reasoning : [];
    const filingWords = (d.thesis && d.thesis.filing_word_search) ? d.thesis.filing_word_search : {{}};
    const keyFinancials = (d.thesis && d.thesis.key_financials) ? d.thesis.key_financials : {{}};
    const checklist = (d.thesis && d.thesis.persona_checklist) ? d.thesis.persona_checklist : {{}};
    const contributions = (d.thesis && d.thesis.score_contribution) ? d.thesis.score_contribution : {{}};
    const weights = (d.thesis && d.thesis.score_weights) ? d.thesis.score_weights : {{}};
    const trends = (d.thesis && d.thesis.three_year_trends) ? d.thesis.three_year_trends : [];
    const risks = (d.risks && d.risks.key_risks) ? d.risks.key_risks : [];
    const filingYears = d.filing_years_analyzed || [];
    const context = d.context || {{}};
    const fmt = (v, digits=2) => (v === null || v === undefined) ? 'N/A' : (typeof v === 'number' ? v.toFixed(digits) : v);
    const compactMoney = (v) => {{
      if (v === null || v === undefined) return 'N/A';
      const n = Number(v);
      if (!Number.isFinite(n)) return 'N/A';
      const abs = Math.abs(n);
      if (abs >= 1_000_000_000) return `${{(n/1_000_000_000).toFixed(2)}} billion`;
      if (abs >= 1_000_000) return `${{(n/1_000_000).toFixed(2)}} million`;
      return n.toFixed(2);
    }};
    const pct = (v) => (v === null || v === undefined) ? 'N/A' : `${{Number(v).toFixed(2)}}%`;
    const checklistHtml = Object.entries(checklist).map(([lens, items]) => `
      <div><b>${{lens}}</b></div>
      <ul>${{(items || []).map(i => `<li><span class="${{i.pass ? 'pass' : 'fail'}}">${{i.pass ? 'PASS' : 'FAIL'}}</span> - ${{i.criterion}} with actual <span class="mono">${{fmt(i.actual)}}</span> compared to threshold <span class="mono">${{i.comparator}} ${{fmt(i.threshold)}}</span>.</li>`).join('')}}</ul>
    `).join('');
    const contributionHtml = Object.entries(contributions).map(([k,v]) => `<li><b>${{k}}</b> contributes <span class="mono">${{fmt(v)}}</span> weighted points (weight <span class="mono">${{fmt(weights[k], 2)}}</span>).</li>`).join('');
    const trendHtml = trends.map(t => `<li>FY${{t.fiscal_year}}: Revenue <b>${{compactMoney(t.revenue)}}</b>, Gross margin <b>${{pct(t.gross_margin)}}</b>, Operating margin <b>${{pct(t.operating_margin)}}</b>, ROE <b>${{pct(t.roe)}}</b>, FCF <b>${{compactMoney(t.fcf)}}</b>, Debt/EBITDA <b>${{fmt(t.debt_to_ebitda)}}</b>, Current ratio <b>${{fmt(t.current_ratio)}}</b>.</li>`).join('');
    const stLabel = item.status === 'recommended' ? 'recommended' : (item.status === 'watchlist' ? 'on the watchlist' : String(item.status || 'listed'));
    const summaryText = 'This name is ' + stLabel + ' with a blended score of ' + item.final_score.toFixed(2) + '. Under the Buffett lens, quality and cash generation remain supportive; Ackman-style quality metrics and operating profile are constructive. The Wood lens focuses on growth trajectory and margin structure, while the Burry lens checks balance-sheet resilience and valuation discipline. Institutional suitability is evaluated through liquidity and scale assumptions.';
    const invNews = d.investor_news || [];
    let newsUl = '';
    for (const n of invNews) {{
      const t = String(n.title || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
      const u = String(n.url || '#').replace(/"/g,'&quot;').replace(/'/g, '&#39;');
      const src = String(n.source_name || '').replace(/&/g,'&amp;').replace(/</g,'&lt;');
      const when = String(n.published_at || '').replace(/&/g,'&amp;');
      const meta = (src || when) ? ('<span class="meta">' + (src || '') + (src && when ? ' · ' : '') + (when || '') + '</span>') : '';
      newsUl += '<li style="margin:8px 0;"><a href="' + u + '" target="_blank" rel="noopener noreferrer" style="color:#7eb8ff;">' + t + '</a> ' + meta + '</li>';
    }}
    const fwd = (d.thesis && d.thesis.investment_case_forward) ? d.thesis.investment_case_forward : {{}};
    const priceLine = (item.last_price != null && item.last_price !== undefined)
      ? `${{Number(item.last_price).toFixed(2)}} ${{item.price_currency || 'USD'}}`
      : 'N/A';
    const dayChg = (item.price_change_pct_day != null && item.price_change_pct_day !== undefined)
      ? `${{Number(item.price_change_pct_day) >= 0 ? '+' : ''}}${{Number(item.price_change_pct_day).toFixed(2)}}%`
      : 'N/A';
    const quoteMeta = item.quote_as_of ? `as of ${{item.quote_as_of}} (${{item.quote_source || 'market'}})` : '';
    return `
      <div class="card">
        <div class="header">
          <div>
            <div class="ticker">${{item.ticker}} <span class="badge">${{item.status}}</span> <span class="badge">${{item.horizon || 'N/A'}}</span></div>
            <div class="meta">${{item.as_of}}</div>
          </div>
          <div class="score">${{item.final_score.toFixed(2)}}</div>
        </div>
        <div class="panel" style="margin-top:10px;">
          <h3>Executive Investment Summary</h3>
          <div style="font-size:13px; color:#d5def0; line-height:1.5;">${{summaryText}}</div>
          <div class="kpi">
            <div class="chip">Last price: <b>${{priceLine}}</b></div>
            <div class="chip">Day change: <b>${{dayChg}}</b></div>
            <div class="chip">Quote: <span class="mono">${{quoteMeta || 'refresh if missing'}}</span></div>
            <div class="chip">Revenue: <b>${{compactMoney(keyFinancials.revenue)}}</b></div>
            <div class="chip">FCF: <b>${{compactMoney(keyFinancials.fcf)}}</b></div>
            <div class="chip">Revenue growth: <b>${{pct(keyFinancials.revenue_growth_pct)}}</b></div>
            <div class="chip">Operating margin: <b>${{pct(keyFinancials.operating_margin)}}</b></div>
            <div class="chip">ROE: <b>${{pct(keyFinancials.roe)}}</b></div>
          </div>
        </div>
        <div class="panel" style="margin-top:10px;">
          <h3>Why invest? Forward-looking rationale</h3>
          <div style="font-size:13px; color:#dbe7ff; line-height:1.5;">${{fwd.headline || 'Forward case will appear after the next full analysis run.'}}</div>
          <ul>${{(fwd.bullets || []).map(b => `<li>${{b}}</li>`).join('')}}</ul>
          <div class="meta">${{fwd.horizon_note || ''}}</div>
          <div class="meta" style="margin-top:8px; font-size:11px;">${{fwd.disclaimer || ''}}</div>
        </div>
        <div class="grid">
          <div class="panel">
            <h3>Why This Is Recommended</h3>
            <ul>${{whyNow.map(x => `<li>${{x}}</li>`).join('')}}</ul>
          </div>
          <div class="panel">
            <h3>Investor Lens Narratives</h3>
            <ul>${{personaReasoning.map(x => `<li>${{x}}</li>`).join('')}}</ul>
          </div>
          <div class="panel">
            <h3>Lens Criteria Audit (Pass/Fail)</h3>
            ${{checklistHtml}}
          </div>
          <div class="panel">
            <h3>Score Attribution</h3>
            <ul>${{contributionHtml}}</ul>
          </div>
          <div class="panel">
            <h3>Three-Year Fundamentals Trend</h3>
            <ul>${{trendHtml}}</ul>
          </div>
          <div class="panel">
            <h3>Filings, Risk, and Secondary Context</h3>
            <ul>
              <li>10-K fiscal years reviewed: <span class="mono">${{filingYears.join(', ') || 'N/A'}}</span></li>
              <li>Filing word signals - risk: <span class="mono">${{filingWords.risk || 0}}</span>, litigation: <span class="mono">${{filingWords.litigation || 0}}</span>, growth: <span class="mono">${{filingWords.growth || 0}}</span>, AI: <span class="mono">${{filingWords.ai || 0}}</span>, debt: <span class="mono">${{filingWords.debt || 0}}</span></li>
              <li>Analyst context score: <span class="mono">${{context.analyst_consensus_score ?? 'N/A'}}</span></li>
              <li>News risk score: <span class="mono">${{context.news_risk_score ?? 'N/A'}}</span></li>
              <li>Search interest score: <span class="mono">${{context.search_interest_score ?? 'N/A'}}</span></li>
            </ul>
            <h3 style="margin-top:10px;">Principal Risks</h3>
            <ul>${{risks.map(x => `<li>${{x}}</li>`).join('')}}</ul>
          </div>
        </div>
        <div class="panel" style="margin-top:12px; border-color:#315082;">
          <h3>Trusted outlet headlines (last 10 days)</h3>
          <div class="meta" style="margin-bottom:8px;">Loaded live on each refresh (same trusted-outlet filter as research policy; not used to auto-block).</div>
          ${{newsUl ? '<ul style="margin:0; padding-left:18px;">' + newsUl + '</ul>' : '<div class="meta">No matching headlines in this window, or the feed is temporarily unavailable. Set NEWSAPI_KEY for domain-filtered coverage.</div>'}}
        </div>
      </div>
    `;
  }}).join('');
  document.getElementById('lastRun').textContent = data[0].as_of;
}}
loadRecs();
</script>
</body>
</html>
        """
    )
