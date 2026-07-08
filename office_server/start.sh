#!/bin/sh
set -eu

# Runs the complete Voxreach voice agent stack (vLLM + livekit-server +
# worker) on a single GPU machine, for local development/testing.
#
# This starts a NON-TLS, localhost-only livekit-server (ws://localhost:7880)
# — it does NOT need a real domain or TLS certs. For production deployment
# (real domain, TLS, systemd auto-restart, multiple workers), use the units
# in deploy/systemd/ instead, which render the production config from
# deploy/livekit/livekit-server.yaml.template via envsubst.
#
# Usage: ./start.sh [path-to-env-file]
# Default env file: ./office.env (copy deploy/env/office.env.example first
# and fill in real LIVEKIT_API_KEY/LIVEKIT_API_SECRET — see that file's
# comments for how to generate them).

ENV_FILE="${1:-./office.env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found: $ENV_FILE" >&2
  echo "Copy deploy/env/office.env.example to $ENV_FILE, fill in real values, and re-run." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${LIVEKIT_API_KEY:?LIVEKIT_API_KEY must be set in $ENV_FILE}"
: "${LIVEKIT_API_SECRET:?LIVEKIT_API_SECRET must be set in $ENV_FILE}"
: "${OFFICE_LLM_MODEL:?OFFICE_LLM_MODEL must be set in $ENV_FILE}"
: "${OFFICE_VLLM_GPU_MEM_UTIL:?OFFICE_VLLM_GPU_MEM_UTIL must be set in $ENV_FILE}"

if [ "$LIVEKIT_API_KEY" = "CHANGE_ME" ] || [ "$LIVEKIT_API_SECRET" = "CHANGE_ME" ]; then
  echo "LIVEKIT_API_KEY/LIVEKIT_API_SECRET are still the CHANGE_ME placeholders." >&2
  echo "Generate real ones with: livekit-server generate-keys" >&2
  exit 1
fi

# Local-only livekit-server config: no TLS, no real domain — the production
# template (deploy/livekit/livekit-server.yaml.template) requires both and
# is deliberately not used here.
LOCAL_LIVEKIT_CONFIG="$(mktemp)"
cat > "$LOCAL_LIVEKIT_CONFIG" <<EOF
port: 7880
rtc:
  tcp_port: 7881
  port_range_start: 50000
  port_range_end: 60000
  use_external_ip: false
keys:
  ${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}
logging:
  level: info
EOF

PIDS=""
cleanup() {
  echo "Stopping services..."
  for pid in $PIDS; do
    kill "$pid" 2>/dev/null || true
  done
  rm -f "$LOCAL_LIVEKIT_CONFIG"
}
trap cleanup INT TERM EXIT

echo "[1/3] Starting vLLM (${OFFICE_LLM_MODEL})..."
vllm serve "$OFFICE_LLM_MODEL" --port 8000 --gpu-memory-utilization "$OFFICE_VLLM_GPU_MEM_UTIL" &
PIDS="$PIDS $!"

echo "Waiting for vLLM to become healthy on :8000..."
until curl -sf http://localhost:8000/health >/dev/null 2>&1; do
  sleep 2
done
echo "vLLM is up."

echo "[2/3] Starting livekit-server (local, no TLS, ws://localhost:7880)..."
livekit-server --config "$LOCAL_LIVEKIT_CONFIG" &
PIDS="$PIDS $!"
sleep 3

echo "[3/3] Starting sdr-agent worker..."
LIVEKIT_URL="ws://localhost:7880" python -m sdr_agent.worker &
PIDS="$PIDS $!"

echo ""
echo "All services running."
echo "  LiveKit URL:    ws://localhost:7880"
echo "  LiveKit API key/secret: from $ENV_FILE"
echo "Connect via the LiveKit Agents Playground or index.html with those values."
echo "Press Ctrl+C to stop everything."
wait
