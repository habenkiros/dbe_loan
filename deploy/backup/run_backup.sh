#!/usr/bin/env bash
# DECSI Loan Hub — nightly backup (database + media).
# Designed to run inside the `backup` Compose service, or from the host via cron.
set -euo pipefail

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-decsiloandb}"
DB_USER="${DB_USER:-decsiloandbuser}"
DB_PASSWORD="${DB_PASSWORD:-decsiloandbpassword}"
MEDIA_PATH="${MEDIA_PATH:-/app/media}"

mkdir -p "$BACKUP_DIR"
WORK="$BACKUP_DIR/.work_$STAMP"
mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

echo "[$(date -Iseconds)] Starting DECSI backup → $BACKUP_DIR"

export PGPASSWORD="$DB_PASSWORD"
pg_dump \
  -h "$DB_HOST" \
  -p "$DB_PORT" \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  --no-owner \
  --no-acl \
  -F c \
  -f "$WORK/database.dump"

pg_dump \
  -h "$DB_HOST" \
  -p "$DB_PORT" \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  --no-owner \
  --no-acl \
  -f "$WORK/database.sql"

if [[ -d "$MEDIA_PATH" ]]; then
  tar -czf "$WORK/media.tar.gz" -C "$(dirname "$MEDIA_PATH")" "$(basename "$MEDIA_PATH")"
else
  echo "[$(date -Iseconds)] WARN: media path missing ($MEDIA_PATH) — DB-only backup"
fi

ARCHIVE="$BACKUP_DIR/decsi_backup_${STAMP}.tar.gz"
tar -czf "$ARCHIVE" -C "$WORK" .
echo "[$(date -Iseconds)] Wrote $ARCHIVE ($(du -h "$ARCHIVE" | awk '{print $1}'))"

# Drop archives older than retention (whole days).
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'decsi_backup_*.tar.gz' -mtime "+${RETENTION_DAYS}" -print -delete \
  || true

echo "[$(date -Iseconds)] Backup finished (retention ${RETENTION_DAYS} days)."
