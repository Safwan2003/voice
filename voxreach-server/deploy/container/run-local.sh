#!/bin/sh
set -eu

# Local dev runner - replaces start.sh. Runs the same container images
# used in production via `podman run` instead of native processes, so
# "test locally" and "run in production" are the same mechanism.
#
# GPU is auto-detected: if `nvidia-smi` is available, the worker
# container gets GPU passthrough and runs real STT/TTS. If not, the
# worker still runs, but in CPU mode (WHISPER_DEVICE=cpu) - correctness
# testing only, far too slow for a real conversation. This does not
# grant GPU access that doesn't exist; it automates the same
# CPU-fallback option that already existed via WHISPER_DEVICE=cpu.
#
# Usage: ./deploy/container/run-local.sh [path-to-env-file]
# Default env file: ./office.env (copy deploy/env/office.env.example first).
# Set SKIP_BUILD=1 to reuse already-built local images instead of rebuilding.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PUBLIC_HOST="${PUBLIC_HOST:-localhost}"

ENV_FILE="${1:-$REPO_ROOT/office.env}"
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
: "${UI_ACCESS_SECRET:?UI_ACCESS_SECRET must be set in $ENV_FILE}"

UI_PORT="${UI_PORT:-8080}"
LIVEKIT_CONTAINER_NAME="voxreach-livekit-server"
UI_CONTAINER_NAME="voxreach-ui"
WORKER_CONTAINER_NAME="voxreach-worker"

if [ "$LIVEKIT_API_KEY" = "CHANGE_ME" ] || [ "$LIVEKIT_API_SECRET" = "CHANGE_ME" ]; then
  echo "LIVEKIT_API_KEY/LIVEKIT_API_SECRET are still CHANGE_ME — generating a real pair..." >&2
  if command -v livekit-server >/dev/null 2>&1; then
    KEYGEN_OUTPUT="$(livekit-server generate-keys)"
  else
    KEYGEN_OUTPUT="$(podman run --rm docker.io/livekit/livekit-server:latest generate-keys)"
  fi
  NEW_KEY="$(echo "$KEYGEN_OUTPUT" | awk -F': *' '/API Key:/{print $2}')"
  NEW_SECRET="$(echo "$KEYGEN_OUTPUT" | awk -F': *' '/API Secret:/{print $2}')"
  sed -i "s/^LIVEKIT_API_KEY=.*/LIVEKIT_API_KEY=${NEW_KEY}/" "$ENV_FILE"
  sed -i "s/^LIVEKIT_API_SECRET=.*/LIVEKIT_API_SECRET=${NEW_SECRET}/" "$ENV_FILE"
  LIVEKIT_API_KEY="$NEW_KEY"
  LIVEKIT_API_SECRET="$NEW_SECRET"
  echo "Generated and saved a new key/secret pair to $ENV_FILE."
fi

if [ "$UI_ACCESS_SECRET" = "CHANGE_ME" ]; then
  NEW_UI_SECRET="$(head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  sed -i "s/^UI_ACCESS_SECRET=.*/UI_ACCESS_SECRET=${NEW_UI_SECRET}/" "$ENV_FILE"
  UI_ACCESS_SECRET="$NEW_UI_SECRET"
  echo "Generated and saved a new UI_ACCESS_SECRET to $ENV_FILE: $NEW_UI_SECRET"
fi

cleanup() {
  echo "Stopping services..."
  podman stop "$LIVEKIT_CONTAINER_NAME" "$UI_CONTAINER_NAME" "$WORKER_CONTAINER_NAME" >/dev/null 2>&1 || true
  podman rm "$LIVEKIT_CONTAINER_NAME" "$UI_CONTAINER_NAME" "$WORKER_CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup INT TERM EXIT

echo "[1/3] Building images (set SKIP_BUILD=1 to reuse existing ones)..."
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  podman build -t voxreach-worker:local -f "$SCRIPT_DIR/worker.Containerfile" "$REPO_ROOT"
  podman build -t voxreach-ui:local -f "$SCRIPT_DIR/ui.Containerfile" "$REPO_ROOT"
fi

echo "[2/3] Starting livekit-server, UI, and worker..."
podman rm -f "$LIVEKIT_CONTAINER_NAME" "$UI_CONTAINER_NAME" "$WORKER_CONTAINER_NAME" >/dev/null 2>&1 || true

podman run -d --name "$LIVEKIT_CONTAINER_NAME" --network host \
  --env LIVEKIT_KEYS="${LIVEKIT_API_KEY}: ${LIVEKIT_API_SECRET}" \
  docker.io/livekit/livekit-server:latest --bind 0.0.0.0 >/dev/null

podman run -d --name "$UI_CONTAINER_NAME" --network host \
  --env-file "$ENV_FILE" \
  voxreach-ui:local >/dev/null

mkdir -p "$REPO_ROOT/.hf-cache"
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "GPU detected — running worker with GPU passthrough."
  podman run -d --name "$WORKER_CONTAINER_NAME" --network host \
    --device nvidia.com/gpu=all \
    --env-file "$ENV_FILE" \
    --env LIVEKIT_URL="ws://localhost:7880" \
    -v "$REPO_ROOT/.hf-cache:/root/.cache/huggingface" \
    voxreach-worker:local >/dev/null
else
  echo "No GPU detected — running worker in CPU mode (WHISPER_DEVICE=cpu)." >&2
  echo "STT/TTS will be too slow for a real call, but the code path is testable." >&2
  podman run -d --name "$WORKER_CONTAINER_NAME" --network host \
    --env-file "$ENV_FILE" \
    --env LIVEKIT_URL="ws://localhost:7880" \
    --env WHISPER_DEVICE=cpu \
    -v "$REPO_ROOT/.hf-cache:/root/.cache/huggingface" \
    voxreach-worker:local >/dev/null
fi

sleep 2
echo ""
echo "[3/3] Ready."
echo "  UI:  http://${PUBLIC_HOST}:${UI_PORT}"
echo "  Enter the shared secret (UI_ACCESS_SECRET in $ENV_FILE) and click 'Get Token' to connect."
echo "Press Ctrl+C to stop everything."
podman wait "$LIVEKIT_CONTAINER_NAME" "$UI_CONTAINER_NAME" "$WORKER_CONTAINER_NAME"
