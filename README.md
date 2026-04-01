# AI Investment Analyst

This is a runnable AI investment analyst product that:
- Uses a multi-investor persona framework (Buffett/Ackman/Wood/Burry/Pelosi proxy + institutional overlay)
- Pulls last 3 years of 10-K filing metadata/text from SEC EDGAR
- Pulls annual financials from SEC Company Facts (XBRL)
- Produces scored stock recommendations and a dashboard with rationale

## Run the product (local)

1. Create a virtual environment and install deps:
   - `cd backend`
   - `python3 -m venv .venv && source .venv/bin/activate`
   - `pip install -r requirements.txt`
2. Set SEC user-agent (required by SEC):
   - `export SEC_USER_AGENT="AIInvestmentAnalyst/0.1 your-email@example.com"`
2. Run API:
   - `uvicorn app.main:app --reload`
3. Open dashboard:
   - `http://127.0.0.1:8000/dashboard`

## One-click workflow

- Open dashboard and click **Run Full Analysis**.
- The system will:
  - sync the stock universe
  - fetch SEC 10-K data + financial metrics
  - score each stock using persona framework
  - display **recommended and watchlist** names, each with **live trusted-outlet headlines** (last ~10 days; refreshes when you reload the dashboard)

## Notes

- **Verify your deploy:** open **`/health/features`** (no login). You should see `auto_block_critical_risk_gate: false` and `investor_news_on_recommendation_detail: true`.
- **Investor news:** optional **`NEWSAPI_KEY`** improves headline quality; outlet filtering uses **`CRITICAL_NEWS_ALLOWLIST`** / **`CRITICAL_NEWS_STRICT_OUTLETS`** (see `backend/.env.example`).
- Live **stock prices** are best-effort: Finnhub (if `FINNHUB_API_KEY`), Yahoo, yfinance, Stooq, Twelve Data, Alpha Vantage (context only; not for order execution). Use `/health/quote` to debug providers on deploy.
- Forward-looking narrative is **illustrative** and stored with each recommendation after analysis runs; it is not a price target or guarantee.
- Uses SQLite by default (`backend/investment_analyst.db`).
- Endpoints are still available at `http://127.0.0.1:8000/docs`.
- For production, add scheduler workers and persistent deployment.

## Operations Runbook

- See `runbook.md` for production operations, monitoring, incident response, and maintenance checklist.

## Cloud deploy (Render, fastest path)

1. Push this folder to a GitHub repo.
2. In Render, click **New +** -> **Blueprint**.
3. Select your repo. Render will detect `render.yaml`.
4. Set these required env vars in Render:
   - `SEC_USER_AGENT` (example: `AIInvestmentAnalyst/0.1 your-email@example.com`)
   - `AUTH_PASSWORD` (your own strong password)
5. Deploy.

After deploy, open:
- `https://<your-render-domain>/login`

Use:
- username: `admin`
- password: your `AUTH_PASSWORD`

## Cloud deploy (Railway)

1. Connect the GitHub repo and deploy. Either:
   - Set the service **Root Directory** to `backend` and start with `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, **or**
   - Keep **repo root** as the service root: `railway.toml` uses **RAILPACK** (Railway’s current builder; do not use `nixpacks`). A root **`requirements.txt`** delegates to `backend` via `-r backend/requirements.txt`; start command `cd backend && uvicorn …`.
2. Add a **Postgres** plugin and set `DATABASE_URL` on the web service (SQLAlchemy style `postgresql+psycopg2://…` is fine).
3. Set `SEC_USER_AGENT`, `AUTH_PASSWORD`, and **`FINNHUB_API_KEY`** (quotes often fail from cloud IPs without it).
4. After deploy, open `https://<your-railway-url>/health/quote?ticker=AAPL` (no login) to see which quote provider succeeded.

For a ready-made message to paste into Railway’s AI assistant, see **`RAILWAY_AI_AGENT_PROMPT.txt`** in the repo root.
