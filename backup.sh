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
mkdir -p "${BACKUP_DIR}"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_FILE="${BACKUP_DIR}/postgres_${TIMESTAMP}.sql"

echo "Backing up database '${POSTGRES_DB}' to ${BACKUP_FILE} ..."

docker compose exec -T postgres pg_dump \
  -U "${POSTGRES_USER}" \
  --clean --if-exists \
  "${POSTGRES_DB}" > "${BACKUP_FILE}"

if [ ! -s "${BACKUP_FILE}" ]; then
  echo "ERROR: backup file is empty, aborting." >&2
  exit 1
fi

echo "Backup complete: ${BACKUP_FILE} ($(wc -l < "${BACKUP_FILE}") lines)"