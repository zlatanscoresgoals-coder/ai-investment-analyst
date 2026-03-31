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

- Open dashboard and click **Run Full Analysis Now**.
- The system will:
  - sync the stock universe
  - fetch SEC 10-K data + financial metrics
  - score each stock using persona framework
  - display recommended names

## Notes

- Live **stock prices** on the dashboard are fetched from Yahoo Finance chart data (context only; not for order execution).
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
