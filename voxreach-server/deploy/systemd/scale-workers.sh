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
  systemctl enable --now "sdr-worker@${i}.service"
  i=$((i + 1))
done

echo "Enabled and started ${NUM_WORKERS} sdr-worker instance(s)"
