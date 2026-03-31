#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR/backend"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt >/dev/null
export SEC_USER_AGENT="${SEC_USER_AGENT:-AIInvestmentAnalyst/0.1 your-email@example.com}"

APP_PORT=8010
if lsof -i :8010 >/dev/null 2>&1; then
  APP_PORT=8011
fi

nohup uvicorn app.main:app --host 0.0.0.0 --port "$APP_PORT" >/tmp/ai-investment-analyst-public-app.log 2>&1 &
sleep 2

if ! curl -s "http://127.0.0.1:$APP_PORT/health/freshness" >/dev/null; then
  echo "App failed to start. Check /tmp/ai-investment-analyst-public-app.log"
  exit 1
fi

echo "App started on local port $APP_PORT"
echo "Starting public tunnel (this can take ~20-40 seconds)..."
echo ""
LT_LOG="/tmp/ai-investment-analyst-localtunnel.log"
rm -f "$LT_LOG"

# Start tunnel in background and capture output.
nohup npx --yes localtunnel --port "$APP_PORT" >"$LT_LOG" 2>&1 &
LT_PID=$!

URL=""
for i in {1..30}; do
  if [ -f "$LT_LOG" ]; then
    URL=$(python3 - <<'PY'
import re
path="/tmp/ai-investment-analyst-localtunnel.log"
try:
    txt=open(path,"r",encoding="utf-8",errors="ignore").read()
except Exception:
    txt=""
m=re.search(r"https://[a-z0-9-]+\.loca\.lt", txt)
print(m.group(0) if m else "")
PY
)
    if [ -n "$URL" ]; then
      break
    fi
  fi
  sleep 2
done

if [ -n "$URL" ]; then
  echo "Public URL ready:"
  echo "$URL/dashboard"
  echo ""
  echo "Local fallback URL:"
  echo "http://127.0.0.1:$APP_PORT/dashboard"
  echo ""
  echo "To stop tunnel later: kill $LT_PID"
else
  echo "Tunnel could not be established automatically."
  echo "Check tunnel logs: $LT_LOG"
  echo "App is still running locally at: http://127.0.0.1:$APP_PORT/dashboard"
fi
