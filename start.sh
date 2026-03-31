#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/backend"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt >/dev/null

# SEC requires a descriptive user agent.
export SEC_USER_AGENT="${SEC_USER_AGENT:-AIInvestmentAnalyst/0.1 your-email@example.com}"

PORT=8000
if lsof -i :8000 >/dev/null 2>&1; then
  PORT=8001
fi

# --reload makes code changes live without restarts.
nohup uvicorn app.main:app --reload --host 127.0.0.1 --port "$PORT" >/tmp/ai-investment-analyst.log 2>&1 &
sleep 2

open "http://127.0.0.1:$PORT/dashboard"
echo "Dashboard opened: http://127.0.0.1:$PORT/dashboard"
