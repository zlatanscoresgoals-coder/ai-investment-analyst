#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/backend"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt >/dev/null

export SEC_USER_AGENT="${SEC_USER_AGENT:-AIInvestmentAnalyst/0.1 your-email@example.com}"

PORT=8010
if lsof -i :8010 >/dev/null 2>&1; then
  PORT=8011
fi

# Bind to all interfaces so phone/laptop on same Wi-Fi can access it.
nohup uvicorn app.main:app --host 0.0.0.0 --port "$PORT" >/tmp/ai-investment-analyst-network.log 2>&1 &
sleep 2

echo ""
echo "Network mode started."
echo "On this Mac: http://127.0.0.1:$PORT/dashboard"
echo ""
echo "To open on phone/laptop (same Wi-Fi):"
echo "1) Find this Mac's local IP (System Settings > Wi-Fi > Details)"
echo "2) Open: http://<YOUR-MAC-IP>:$PORT/dashboard"
echo ""
