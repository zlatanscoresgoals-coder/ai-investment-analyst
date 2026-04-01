# AI Investment Analyst Runbook

## 1) Daily Operations (2 minutes)

- Open `/login` and sign in.
- Open `/dashboard` and confirm data loads (recommended **and** watchlist names, with **Trusted outlet headlines** on each card).
- Open `/health/freshness` and check:
  - `auto_refresh_enabled` is `true`
  - `last_run_at` is recent
  - `last_status` is `ok`
- After each deploy, open **`/health/features`** (no login) and confirm:
  - `auto_block_critical_risk_gate` is `false`
  - `investor_news_on_recommendation_detail` is `true`
  - `startup_migrate_blocked_to_watchlist` is `true`

If `last_run_at` is stale, trigger **Run Full Analysis** from dashboard.

## Market quotes (live price)

- The app tries **Finnhub** (if `FINNHUB_API_KEY` is set), then **Yahoo**, then **Stooq**.
- **Railway/datacenter IPs are often blocked by Yahoo** — set a free Finnhub key in Railway Variables for reliable prices.
- Quotes are for **context only**, not execution prices.
- Filings and fundamentals remain SEC-first; market prices are a separate layer.

## Investor news (trusted outlets, ~10 days)

- Each stock’s **detail** (`GET /recommendations/{TICKER}`) includes **`investor_news`**: live headlines, refetched on every request (not stored in DB).
- The dashboard loads detail per ticker on **Refresh**, so headlines update then.
- **Optional:** set **`NEWSAPI_KEY`** for NewsAPI domain-filtered results; otherwise the app uses Google News RSS + the same substring allowlist as `CRITICAL_NEWS_ALLOWLIST`.
- **`CRITICAL_NEWS_STRICT_OUTLETS`** / **`CRITICAL_NEWS_ALLOWLIST`** control which outlets count as “trusted” for that panel.

## 2) Production Configuration (Railway)

Required variables:

- `SEC_USER_AGENT=AIInvestmentAnalyst/0.1 your-email@example.com`
- `DATABASE_URL=<postgresql+psycopg2 connection string>`
- `AUTH_ENABLED=true`
- `AUTH_USERNAME=admin`
- `AUTH_PASSWORD=<strong-secret>`
- `AUTO_REFRESH_ENABLED=true`
- `AUTO_REFRESH_INTERVAL_MINUTES=15`

Optional:

- `NEWSAPI_KEY` — better headline coverage for `investor_news`
- `ALERT_WEBHOOK_URL=<slack/discord/teams webhook>` (if you add alerting later)
- `RISK_BLOCK_MIN_CONFIDENCE` — legacy setting; auto-block from the old critical gate is **off** in current builds

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

## 5) Legacy: blocked status and `/portfolio/impact`

- The pipeline **no longer** auto-blocks tickers via the old critical risk gate.
- On **app startup**, any recommendation row still in status **`blocked`** is rewritten to **`watchlist`** so names reappear in lists and the dashboard.
- **`/portfolio/impact`** still reports `blocked_*` counts for debugging **legacy** DB rows only; expect zeros after a restart on a current build.

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
4. Open `/dashboard` — watchlist names are shown too; check **`/recommendations?status=watchlist`**.

### D) Stale data

1. Confirm scheduler still running (`last_run_at` moving).
2. Reduce refresh interval temporarily.
3. Check external source availability (SEC/news APIs).

### E) “Wrong” or empty investor news

1. Set `NEWSAPI_KEY` and redeploy; hit `/health/features` → `newsapi_configured: true`.
2. Loosen or extend `CRITICAL_NEWS_ALLOWLIST` if too few outlets match.

## 7) Deploy Checklist

Before deploy:

- Confirm changes are pushed to `main`.
- Ensure secrets are not hardcoded.
- Verify `render.yaml`/Railway config compatibility.

After deploy:

- `/login` reachable
- **`/health/features`** matches expected flags
- `/dashboard` loads
- `/health/freshness` shows healthy scheduler
- Trigger one manual full run and verify output

## 8) Weekly Maintenance

- Spot-check `/dashboard` headline panels for a few tickers.
- Rotate password if needed.
- Validate DB backups/export strategy.
- Review logs for recurring ingestion failures.

## 9) Recovery Notes

- Keep one known-good commit hash and deployment timestamp.
- If a bad deploy occurs, roll back to previous successful deploy in Railway.
- Re-run full analysis after rollback to refresh consistency.
