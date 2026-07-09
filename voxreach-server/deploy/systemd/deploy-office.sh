#!/bin/sh
set -eu

# Deploys the worker, UI, and livekit-server to the office box as
# systemd-managed services (Podman Quadlets for worker/UI, a native
# process for livekit-server). Idempotent - safe to re-run for a first
# install, an office.env edit, or a CI-triggered redeploy after a new
# image is pushed to GHCR (see .github/workflows/ci.yml's `deploy` job,
# which runs this script on the office box's self-hosted runner on every
# merge to main).
#
# Assumes: Podman + NVIDIA Container Toolkit already set up (see
# ../../README.md step 1 of the "Deferred to a human" GPU checks), a
# Cloudflare Tunnel already routing to this box (this script does not
# touch cloudflared's config - see ../../README.md step 4), and
# `podman login ghcr.io` already done so pulls succeed.
#
# Usage: sudo ./deploy-office.sh [path-to-office.env]
# Default env file: /etc/sdr-agent/office.env

if [ "$(id -u)" -ne 0 ]; then
  echo "Must run as root (sudo) - installs systemd units, Quadlets, and restarts services." >&2
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

echo "[1/7] Checking $ENV_FILE for unfilled placeholders..."
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

echo "[2/7] Installing Podman Quadlets (worker + UI)..."
mkdir -p /etc/containers/systemd
cp "$REPO_ROOT/deploy/systemd/sdr-worker@.container" \
   "$REPO_ROOT/deploy/systemd/voxreach-ui.container" \
   /etc/containers/systemd/
systemctl daemon-reload

echo "[3/7] Pulling latest worker/UI images..."
# Quadlet's default Pull policy only fetches an image if none is cached
# locally - it won't re-pull `:latest` on its own, so a plain `systemctl
# restart` after a CI build wouldn't actually run the new image without
# this. Image names are read from the Quadlet files rather than
# hardcoded here, so this works unchanged regardless of which GHCR
# org/repo the images are published under.
WORKER_IMAGE="$(grep '^Image=' "$REPO_ROOT/deploy/systemd/sdr-worker@.container" | cut -d= -f2-)"
UI_IMAGE="$(grep '^Image=' "$REPO_ROOT/deploy/systemd/voxreach-ui.container" | cut -d= -f2-)"
podman pull "$WORKER_IMAGE"
podman pull "$UI_IMAGE"

echo "[4/7] Installing livekit-server systemd unit..."
cp "$REPO_ROOT/deploy/systemd/livekit-server.service" /etc/systemd/system/
systemctl daemon-reload
# enable (idempotent) then restart rather than `enable --now`: on an
# already-running unit `--now` is just a `start`, a no-op that wouldn't
# apply a config change. `restart` handles both first-run and redeploy.
systemctl enable livekit-server.service
systemctl restart livekit-server.service

echo "[5/7] Creating Hugging Face weights cache directory (persists across image updates)..."
mkdir -p /opt/sdr-agent/hf-cache

echo "[6/7] Restarting the UI/token service..."
systemctl enable voxreach-ui.service
systemctl restart voxreach-ui.service

echo "[7/7] Restarting worker instance(s) (OFFICE_NUM_WORKERS=${OFFICE_NUM_WORKERS:-1})..."
"$REPO_ROOT/deploy/systemd/scale-workers.sh" "$ENV_FILE"

echo ""
echo "Deployed. First-ever worker start downloads STT/TTS weights into"
echo "/opt/sdr-agent/hf-cache - watch progress with:"
echo "  journalctl -u sdr-worker@1.service -f"
echo ""
echo "One-time manual step (not automated here): add ingress rules to"
echo "cloudflared's config.yml - see README.md 'Deploy to production' step 4."
