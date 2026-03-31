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

PORT=8012
while lsof -i :"$PORT" >/dev/null 2>&1; do
  PORT=$((PORT + 1))
done

# Start app for LAN access from phone/laptop.
nohup uvicorn app.main:app --host 0.0.0.0 --port "$PORT" >/tmp/ai-investment-analyst-phone.log 2>&1 &
sleep 2

if ! curl -s "http://127.0.0.1:$PORT/login" >/dev/null; then
  echo "App failed to start. Check /tmp/ai-investment-analyst-phone.log"
  exit 1
fi

HOSTNAME_LOCAL="$(scutil --get LocalHostName 2>/dev/null || true)"
LAN_IP="$(python3 - <<'PY'
import socket
ip = ""
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
except Exception:
    pass
print(ip)
PY
)"

echo ""
echo "AI Investment Analyst is running."
echo "Login: admin / GoatAnalyst99"
echo ""
echo "On this Mac:"
echo "http://127.0.0.1:$PORT/login"
echo ""
echo "From phone/laptop on same Wi-Fi:"
if [ -n "$LAN_IP" ]; then
  echo "http://$LAN_IP:$PORT/login"
fi
if [ -n "$HOSTNAME_LOCAL" ]; then
  echo "http://$HOSTNAME_LOCAL.local:$PORT/login"
fi
echo ""
