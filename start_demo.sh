#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  Umurinzi — local demo server
#  Run:  bash start_demo.sh
#
#  Starts gunicorn + Cloudflare Tunnel so the app is publicly
#  accessible at a permanent HTTPS URL with no cold starts.
#  Your Mac must stay awake and plugged in while serving.
# ──────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv/bin"
PORT=5050
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# ── 1. Kill any previous instances ───────────────────────────
echo "[demo] stopping any previous gunicorn / cloudflared …"
pkill -f "gunicorn app_cadastral" 2>/dev/null || true
pkill -f "cloudflared tunnel"     2>/dev/null || true
sleep 1

# ── 2. Prevent Mac from sleeping while server is running ─────
#  caffeinate -s keeps the system awake only while this script
#  is running (or until you press Ctrl+C).
echo "[demo] enabling caffeinate (Mac will not sleep) …"
caffeinate -s &
CAFF_PID=$!

cleanup() {
    echo ""
    echo "[demo] shutting down …"
    pkill -f "gunicorn app_cadastral" 2>/dev/null || true
    pkill -f "cloudflared tunnel"     2>/dev/null || true
    kill "$CAFF_PID" 2>/dev/null || true
    echo "[demo] done."
}
trap cleanup EXIT INT TERM

# ── 3. Start gunicorn ─────────────────────────────────────────
echo "[demo] starting gunicorn on port $PORT …"
"$VENV/gunicorn" app_cadastral:app \
    --workers 2 \
    --timeout 90 \
    --bind "0.0.0.0:$PORT" \
    --access-logfile "$LOG_DIR/access.log" \
    --error-logfile  "$LOG_DIR/error.log" &
GUNICORN_PID=$!

# Wait for gunicorn to be ready (model loads in ~10–15 s)
echo "[demo] waiting for app to boot (model load takes ~15 s) …"
for i in $(seq 1 30); do
    if curl -s "http://localhost:$PORT/api/me" >/dev/null 2>&1; then
        echo "[demo] app is up."
        break
    fi
    sleep 1
done

# ── 4. Start Cloudflare Tunnel ────────────────────────────────
#  If you have a named tunnel (cloudflared tunnel create umurinzi),
#  replace "--url" with "--tunnel umurinzi".
#  Quick tunnel (no account) gives a random URL — fine for one-off demos.
echo ""
echo "[demo] starting Cloudflare Tunnel …"
echo "[demo] your public URL will appear below in ~5 seconds:"
echo ""
cloudflared tunnel --url "http://localhost:$PORT" 2>&1 | tee "$LOG_DIR/tunnel.log" &

# ── 5. Keep running until Ctrl+C ─────────────────────────────
echo ""
echo "──────────────────────────────────────────────"
echo "  Umurinzi is live.  Press Ctrl+C to stop."
echo "  Local:   http://localhost:$PORT"
echo "  Logs:    $LOG_DIR/"
echo "──────────────────────────────────────────────"
wait $GUNICORN_PID
