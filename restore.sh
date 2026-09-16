#!/usr/bin/env bash
set -euo pipefail

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:?POSTGRES_USER not set (check your .env)}"
POSTGRES_DB="${POSTGRES_DB:?POSTGRES_DB not set (check your .env)}"

BACKUP_DIR="backups"
BACKUP_FILE="${1:-}"
if [ -z "${BACKUP_FILE}" ]; then
  BACKUP_FILE="$(ls -t "${BACKUP_DIR}"/postgres_*.sql 2>/dev/null | head -n 1)"
fi

if [ -z "${BACKUP_FILE}" ] || [ ! -f "${BACKUP_FILE}" ]; then
  echo "ERROR: no backup file found. Usage: ./restore.sh [path/to/backup.sql]" >&2
  exit 1
fi

echo "Restoring database '${POSTGRES_DB}' from ${BACKUP_FILE} ..."

docker compose exec -T postgres psql \
  -U "${POSTGRES_USER}" \
  -d "${POSTGRES_DB}" \
  < "${BACKUP_FILE}"

echo "Restore command finished. Verify application data with curl/validate.py."