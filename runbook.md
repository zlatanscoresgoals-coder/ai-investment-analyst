# AI Investment Analyst Runbook

## 1) Daily Operations (2 minutes)

- Open `/login` and sign in.
- Open `/dashboard` and confirm data loads.
- Open `/health/freshness` and check:
  - `auto_refresh_enabled` is `true`
  - `last_run_at` is recent
  - `last_status` is `ok`

If `last_run_at` is stale, trigger **Run Full Analysis** from dashboard.

## Market quotes (live price)

- The dashboard shows a **last price** and **day change** sourced from Yahoo Finance chart data (best-effort).
- Quotes are for **context only**, not execution prices; latency and accuracy depend on Yahoo and network conditions.
- Filings and fundamentals remain SEC-first; market prices are a separate layer.

## 2) Production Configuration (Railway)

Required variables:

- `SEC_USER_AGENT=AIInvestmentAnalyst/0.1 your-email@example.com`
- `DATABASE_URL=<postgresql+psycopg2 connection string>`
- `AUTH_ENABLED=true`
- `AUTH_USERNAME=admin`
- `AUTH_PASSWORD=<strong-secret>`
- `AUTO_REFRESH_ENABLED=true`
- `AUTO_REFRESH_INTERVAL_MINUTES=15`
- `RISK_BLOCK_MIN_CONFIDENCE=medium`

Optional:

- `ALERT_WEBHOOK_URL=<slack/discord/teams webhook>`

## 3) Security Checklist

- Rotate `AUTH_PASSWORD` immediately if shared.
- Keep login URL private for trusted users only.
- Prefer long random password; avoid reused credentials.
- Keep `AUTH_ENABLED=true` in all environments exposed to internet.
- Do not commit real `.env` secrets to git.

## 4) Refresh and Data Freshness

- Default cadence: every `15` minutes.
- For higher responsiveness: set `AUTO_REFRESH_INTERVAL_MINUTES=5` (watch resource usage).
- Validate scheduler health after every deploy in `/health/freshness`.

## 5) Critical Risk Gate Workflow

Monitoring endpoints:

- `/alerts/critical`
- `/portfolio/impact`

Workflow states:

- `blocked` (automatic on critical confidence threshold)
- `under_review`
- `confirmed`
- `unblocked`

Use:

- `POST /alerts/{alert_id}/workflow?action=under_review|confirmed|unblocked`

When unblocking, verify thesis and risk context before moving a stock back to watchlist/recommended state.

## 6) Incident Response

### A) Dashboard unavailable

1. Check service logs in Railway.
2. Verify start command:
   - `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Verify root directory is `backend`.
4. Redeploy latest commit.

### B) Login failing

1. Confirm `AUTH_USERNAME` and `AUTH_PASSWORD` in Railway variables.
2. Redeploy after variable changes.
3. Clear browser cookies or test in private window.

### C) No recommendations

1. Run **Full Analysis** manually.
2. Check `/health/freshness` for run errors.
3. Confirm `DATABASE_URL` is valid and database reachable.
4. Inspect critical alerts (`/alerts/critical`) in case names were blocked.

### D) Stale data

1. Confirm scheduler still running (`last_run_at` moving).
2. Reduce refresh interval temporarily.
3. Check external source availability (SEC/news APIs).

## 7) Deploy Checklist

Before deploy:

- Confirm changes are pushed to `main`.
- Ensure secrets are not hardcoded.
- Verify `render.yaml`/Railway config compatibility.

After deploy:

- `/login` reachable
- `/dashboard` loads
- `/health/freshness` shows healthy scheduler
- Trigger one manual full run and verify output

## 8) Weekly Maintenance

- Review `/alerts/critical` and workflow statuses.
- Review blocked tickers in `/portfolio/impact`.
- Rotate password if needed.
- Validate DB backups/export strategy.
- Review logs for recurring ingestion failures.

## 9) Recovery Notes

- Keep one known-good commit hash and deployment timestamp.
- If a bad deploy occurs, roll back to previous successful deploy in Railway.
- Re-run full analysis after rollback to refresh consistency.
