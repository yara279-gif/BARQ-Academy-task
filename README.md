<img src="assets/barq-logo.svg" alt="BARQ Systems" width="180">

# BARQ Assessment — Setup, Test, Failure, Backup/Restore, Cleanup

Final port after the live challenge: **8090**. Before that: **8080**.

## Prerequisites

- Docker Desktop (Linux containers), Docker Compose v2
- Git, Git Bash (for the `.sh` scripts on Windows)
- Python 3

## Setup

```bash
git clone https://github.com/yara279-gif/BARQ-Academy-task.git
cd BARQ-Academy-task
cp .env.example .env
# then edit .env and set a real POSTGRES_PASSWORD (never commit this file — it's gitignored)
```

## Build & start

```bash
docker compose build
docker compose up -d
docker compose ps
```

Wait until all five containers (`app-01`, `app-02`, `postgres`, `redis`, `nginx`) show
`healthy`/`Up`. `nginx` should show `127.0.0.1:8080->80/tcp` in the PORTS column.

## Test

Manual endpoint checks:

```bash
curl http://127.0.0.1:8080/
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/ready
curl http://127.0.0.1:8080/instance
curl http://127.0.0.1:8080/counter
curl -X POST http://127.0.0.1:8080/records -H "Content-Type: application/json" -d '{"title":"example"}'
curl http://127.0.0.1:8080/records
```

Full automated validation (public access, all endpoints, both backends, PostgreSQL/Redis
readiness, network isolation, no published DB ports — PASS/FAIL, non-zero exit on failure):

```bash
python validate.py
```

App-only unit tests (fake dependencies, no Docker/network required):

```bash
python3 -m venv .venv
source .venv/bin/activate   # Git Bash; on Windows cmd use .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Failure / recovery test

Stops one backend, proves the service stays available through the other, measures
traffic/errors during the outage, restarts the backend, proves it serves traffic again:

```bash
python failure_test.py
```

## Backup / restore

Run from Git Bash:

```bash
./backup.sh            # creates backups/postgres_<UTC-timestamp>.sql (gitignored)
./restore.sh            # restores the most recent backup; or: ./restore.sh path/to/file.sql
```

To prove a backup genuinely restores lost data: create a record via `/records`, run
`./backup.sh`, deliberately drop the schema
(`docker compose exec -T postgres psql -U <user> -d <db> -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"`),
confirm `/records` fails, run `./restore.sh`, confirm the record is back.

## CI

`.github/workflows/ci.yml` runs on every push/PR: checks out the repo, builds the images,
starts the stack with disposable test credentials, waits for it to respond, then runs
`validate.py` — the workflow fails if any check fails.

## Cleanup

```bash
docker compose down          # stops and removes containers, KEEPS the named volumes/data
docker compose down -v       # also deletes volumes — only when you intend to wipe all data
```

Do **not** run `docker compose down` to reset `video_challenge.sh` — it must run exactly
once, live, during the video, and is not part of routine cleanup.

## Troubleshooting: NGINX won't bind to port 8080

If `nginx` fails to start with a port-binding error, something else on the host (commonly
XAMPP's Apache) already owns port 8080. On Windows:
netstat -ano | findstr :8080
tasklist /FI "PID eq <pid>"


Kill it from an **Administrator** command prompt:

taskkill /PID <pid> /F


Then `docker compose up -d` again. See `troubleshooting.md` for real occurrences of this
during this assessment.