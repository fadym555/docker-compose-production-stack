#!/bin/sh
# Periodic pg_dump with rotation. Runs one backup on start, then every BACKUP_INTERVAL_SECONDS.
set -eu

interval="${BACKUP_INTERVAL_SECONDS:-86400}"
keep="${BACKUP_KEEP:-7}"

while true; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  file="/backups/${PGDATABASE}-${stamp}.sql.gz"
  pg_dump --no-owner | gzip > "${file}.tmp"
  mv "${file}.tmp" "${file}"
  echo "backup written: ${file}"
  find /backups -name '*.sql.gz' -type f | sort -r | tail -n +"$((keep + 1))" | xargs -r rm -f
  sleep "${interval}"
done
