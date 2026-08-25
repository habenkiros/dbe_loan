#!/usr/bin/env bash
# Sleep until next local midnight, then run backup (TZ from env, default Addis Ababa).
set -euo pipefail

export TZ="${TZ:-Africa/Addis_Ababa}"

echo "[$(date -Iseconds)] DECSI backup scheduler started (TZ=$TZ)."
echo "[$(date -Iseconds)] Next run at local midnight; use: docker compose run --rm backup /scripts/run_backup.sh for a manual run."

while true; do
  now="$(date +%s)"
  # GNU date (Debian/Postgres image): seconds until tomorrow 00:00 local time
  next="$(date -d 'tomorrow 00:00' +%s)"
  wait_secs=$((next - now))
  if (( wait_secs < 1 )); then
    wait_secs=60
  fi
  echo "[$(date -Iseconds)] Sleeping ${wait_secs}s until midnight…"
  sleep "$wait_secs"
  echo "[$(date -Iseconds)] Midnight — starting backup."
  /scripts/run_backup.sh || echo "[$(date -Iseconds)] ERROR: backup failed (exit $?); will retry tomorrow."
done
