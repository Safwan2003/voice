#!/bin/sh
set -eu

ENV_FILE="${1:-/etc/sdr-agent/office.env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found: $ENV_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
. "$ENV_FILE"
NUM_WORKERS="${OFFICE_NUM_WORKERS:-1}"

i=1
while [ "$i" -le "$NUM_WORKERS" ]; do
  # enable (idempotent, no-op if already enabled) then restart rather than
  # `enable --now`: on an already-running unit, `--now` is a `start`,
  # which is a no-op and won't pick up a freshly pulled image. `restart`
  # covers both first-run (starts a stopped unit) and redeploy (actually
  # restarts to pick up the new image) with one code path.
  systemctl enable "sdr-worker@${i}.service"
  systemctl restart "sdr-worker@${i}.service"
  i=$((i + 1))
done

echo "Enabled and started ${NUM_WORKERS} sdr-worker instance(s)"
