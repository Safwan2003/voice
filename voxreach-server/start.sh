#!/bin/sh
set -eu

# Runs the complete Voxreach voice agent stack (livekit-server + worker;
# the worker's LLM is a hosted API, see OFFICE_LLM_PROVIDER in office.env)
# for local development/testing, then generates a test token and serves
# the UI — so this one command leaves you with a ready-to-click link, not
# just backend services.
#
# livekit-server itself needs no GPU. If the livekit-server binary isn't
# installed, this script runs it via Podman instead (official image,
# pulled automatically) — no manual install required for that piece.
# The actual STT/TTS model loading DOES need a real GPU; nothing here
# changes that. The LLM is a hosted API call — no GPU or local process.
#
# This starts a NON-TLS livekit-server bound to all interfaces (still no
# real domain or TLS certs needed). The printed link uses PUBLIC_HOST for
# the address other devices should connect to (defaults to "localhost",
# i.e. same-machine-only); everything talks to everything else internally
# over localhost regardless — only the link handed to a remote browser
# needs the real address. Set PUBLIC_HOST to this machine's LAN IP (see
# ../README.md "Access from another device on your LAN") to let another
# machine connect. For production deployment (real domain, TLS, systemd
# auto-restart, multiple workers), use the units in deploy/systemd/
# instead, which render the production config from
# deploy/livekit/livekit-server.yaml.template via envsubst.
#
# Usage: ./start.sh [path-to-env-file]
# Default env file: ./office.env (copy deploy/env/office.env.example first).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UI_PORT="${UI_PORT:-8080}"
PUBLIC_HOST="${PUBLIC_HOST:-localhost}"
LIVEKIT_CONTAINER_NAME="voxreach-livekit-server"

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

# Defaults to groq (config.py's own default) so an env file that omits
# OFFICE_LLM_PROVIDER entirely still resolves the same way the worker will.
# The worker validates the matching *_API_KEY itself at startup.
OFFICE_LLM_PROVIDER="${OFFICE_LLM_PROVIDER:-groq}"

# Self-service key generation: if the placeholders are still in place,
# generate a real pair (native binary if present, else via Podman) and
# save it back into the env file so future runs reuse the same identity.
if [ "$LIVEKIT_API_KEY" = "CHANGE_ME" ] || [ "$LIVEKIT_API_SECRET" = "CHANGE_ME" ]; then
  echo "LIVEKIT_API_KEY/LIVEKIT_API_SECRET are still CHANGE_ME — generating a real pair..."
  if command -v livekit-server >/dev/null 2>&1; then
    KEYGEN_OUTPUT="$(livekit-server generate-keys)"
  elif command -v podman >/dev/null 2>&1; then
    KEYGEN_OUTPUT="$(podman run --rm docker.io/livekit/livekit-server:latest generate-keys)"
  else
    echo "Neither livekit-server nor podman is available to generate keys." >&2
    echo "Install one of them, or fill in LIVEKIT_API_KEY/LIVEKIT_API_SECRET manually in $ENV_FILE." >&2
    exit 1
  fi
  NEW_KEY="$(echo "$KEYGEN_OUTPUT" | awk -F': *' '/API Key:/{print $2}')"
  NEW_SECRET="$(echo "$KEYGEN_OUTPUT" | awk -F': *' '/API Secret:/{print $2}')"
  sed -i "s/^LIVEKIT_API_KEY=.*/LIVEKIT_API_KEY=${NEW_KEY}/" "$ENV_FILE"
  sed -i "s/^LIVEKIT_API_SECRET=.*/LIVEKIT_API_SECRET=${NEW_SECRET}/" "$ENV_FILE"
  LIVEKIT_API_KEY="$NEW_KEY"
  LIVEKIT_API_SECRET="$NEW_SECRET"
  echo "Generated and saved a new key/secret pair to $ENV_FILE."
fi

USE_PODMAN_LIVEKIT=0
PIDS=""
cleanup() {
  echo "Stopping services..."
  for pid in $PIDS; do
    kill "$pid" 2>/dev/null || true
  done
  if [ "$USE_PODMAN_LIVEKIT" = "1" ]; then
    podman stop "$LIVEKIT_CONTAINER_NAME" >/dev/null 2>&1 || true
    podman rm "$LIVEKIT_CONTAINER_NAME" >/dev/null 2>&1 || true
  fi
}
trap cleanup INT TERM EXIT

echo "[1/3] LLM: ${OFFICE_LLM_PROVIDER} (hosted API — no local process to start)."

LIVEKIT_KEYS_VALUE="${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}"

if command -v livekit-server >/dev/null 2>&1; then
  echo "[2/3] Starting livekit-server (native binary, no TLS, ws://localhost:7880)..."
  LIVEKIT_KEYS="$LIVEKIT_KEYS_VALUE" livekit-server --bind 0.0.0.0 &
  PIDS="$PIDS $!"
elif command -v podman >/dev/null 2>&1; then
  echo "[2/3] Starting livekit-server (via Podman, no TLS, ws://localhost:7880)..."
  podman rm -f "$LIVEKIT_CONTAINER_NAME" >/dev/null 2>&1 || true
  podman run -d --name "$LIVEKIT_CONTAINER_NAME" --network host \
    --env LIVEKIT_KEYS="$LIVEKIT_KEYS_VALUE" \
    docker.io/livekit/livekit-server:latest --bind 0.0.0.0 >/dev/null
  USE_PODMAN_LIVEKIT=1
else
  echo "Neither the livekit-server binary nor podman is available." >&2
  echo "Install livekit-server, or install podman (https://podman.io) and re-run." >&2
  exit 1
fi
sleep 3

echo "[3/3] Starting sdr-agent worker, generating a test token, and serving the UI..."
LIVEKIT_URL="ws://localhost:7880" python -m sdr_agent.worker &
PIDS="$PIDS $!"
sleep 2

TEST_TOKEN="$(python "$SCRIPT_DIR/scripts/generate-test-token.py" --raw)"

python3 -m http.server "$UI_PORT" --bind 0.0.0.0 --directory "$SCRIPT_DIR/ui" >/dev/null 2>&1 &
PIDS="$PIDS $!"
sleep 1

ENCODED_URL="$(printf 'ws://%s:7880' "$PUBLIC_HOST" | sed 's|:|%3A|g; s|/|%2F|g')"
READY_LINK="http://${PUBLIC_HOST}:${UI_PORT}/index.html?url=${ENCODED_URL}&token=${TEST_TOKEN}"

LIVEKIT_LABEL="native binary"
[ "$USE_PODMAN_LIVEKIT" = "1" ] && LIVEKIT_LABEL="via Podman"

echo ""
echo "All services running:"
echo "  LLM:            ${OFFICE_LLM_PROVIDER} (hosted API)"
echo "  livekit-server: ws://${PUBLIC_HOST}:7880 (${LIVEKIT_LABEL})"
echo "  UI + token pre-filled:"
echo "  ${READY_LINK}"
echo ""
if [ "$PUBLIC_HOST" = "localhost" ]; then
  echo "This link only works from this machine. To reach it from another"
  echo "device on your LAN, set PUBLIC_HOST to this machine's LAN IP and"
  echo "re-run (see README.md \"Access from another device on your LAN\")."
fi
echo "Open that link in a browser and click Connect."
echo "Press Ctrl+C to stop everything."
wait
