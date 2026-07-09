#!/bin/sh
set -eu

# Deploys the worker, UI, and livekit-server to the office box as
# systemd-managed services (Podman Quadlets for worker/UI, a native
# process for livekit-server). Idempotent - safe to re-run after an
# office.env edit or a repo update.
#
# Assumes: Podman + NVIDIA Container Toolkit already set up (see
# ../../README.md step 1 of the "Deferred to a human" GPU checks), and a
# Cloudflare Tunnel already routing to this box (this script does not
# touch cloudflared's config - see ../../README.md step 3).
#
# Usage: sudo ./deploy-office.sh [path-to-office.env]
# Default env file: /etc/sdr-agent/office.env

if [ "$(id -u)" -ne 0 ]; then
  echo "Must run as root (sudo) - installs systemd units and Quadlets." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${1:-/etc/sdr-agent/office.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found: $ENV_FILE" >&2
  echo "Copy deploy/env/office.env.example to $ENV_FILE, fill in real values, and re-run." >&2
  exit 1
fi

echo "[1/6] Checking $ENV_FILE for unfilled placeholders..."
# shellcheck disable=SC1090
. "$ENV_FILE"
MISSING=""
for var_name in LIVEKIT_URL LIVEKIT_API_KEY LIVEKIT_API_SECRET UI_ACCESS_SECRET \
    LIVEKIT_TURN_HOST LIVEKIT_TURN_USERNAME LIVEKIT_TURN_CREDENTIAL; do
  eval "value=\${${var_name}:-}"
  if [ -z "$value" ] || [ "$value" = "CHANGE_ME" ]; then
    MISSING="$MISSING $var_name"
  fi
done
if [ -n "$MISSING" ]; then
  echo "These are still unset or CHANGE_ME in $ENV_FILE:$MISSING" >&2
  echo "Fill them in before deploying - see README.md 'Deploy to production'." >&2
  exit 1
fi

echo "[2/6] Installing Podman Quadlets (worker + UI)..."
mkdir -p /etc/containers/systemd
cp "$REPO_ROOT/deploy/systemd/sdr-worker@.container" \
   "$REPO_ROOT/deploy/systemd/voxreach-ui.container" \
   /etc/containers/systemd/

echo "[3/6] Installing livekit-server systemd unit..."
cp "$REPO_ROOT/deploy/systemd/livekit-server.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now livekit-server.service

echo "[4/6] Creating Hugging Face weights cache directory (persists across image updates)..."
mkdir -p /opt/sdr-agent/hf-cache

echo "[5/6] Starting the UI/token service..."
systemctl enable --now voxreach-ui.service

echo "[6/6] Starting worker instance(s) (OFFICE_NUM_WORKERS=${OFFICE_NUM_WORKERS:-1})..."
"$REPO_ROOT/deploy/systemd/scale-workers.sh" "$ENV_FILE"

echo ""
echo "Deployed. First worker start downloads STT/TTS weights into"
echo "/opt/sdr-agent/hf-cache - watch progress with:"
echo "  journalctl -u sdr-worker@1.service -f"
echo ""
echo "Remaining manual step (not automated here): add ingress rules to"
echo "cloudflared's config.yml - see README.md 'Deploy to production' step 3."
