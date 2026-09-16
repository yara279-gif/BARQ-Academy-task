# Security and production-readiness review

## Finding 1 — Container ran as root and copied the real secret into the image
- Risk and evidence: original `Dockerfile` had `USER root` and
  `COPY config/app.env /srv/app.env` — the running container had root privileges and a
  copy of the real database password baked into an image layer, retrievable by anyone
  with access to the image (`docker save`, registry pull, etc.), independent of the
  running container.
- Impact: if the app process were compromised (e.g. a dependency RCE), the attacker
  would have root inside the container and a plaintext copy of the DB credential
  regardless of how the container was started.
- Implemented fix / commit: `USER app`, removed the `COPY`; commit `ede8940`.
- Production follow-up: run with a read-only root filesystem and drop all Linux
  capabilities not explicitly needed (`cap_drop: ALL`).
- How to verify: `docker compose exec app-01 whoami` → `app`;
  `docker compose exec app-01 sh -c "ls /srv/app.env"` → No such file or directory.

## Finding 2 — Same secret duplicated in two places, causing drift
- Risk and evidence: `POSTGRES_PASSWORD` was hardcoded separately in
  `docker-compose.yml` and in `config/app.env`; they fell out of sync (Stage 2), which
  is itself a real incident that happened during this assessment, not a hypothetical.
- Impact: silent authentication failures against PostgreSQL; in production this pattern
  causes outages exactly when a credential is rotated in only one place.
- Implemented fix / commit: single root `.env` as the only source, referenced via
  `${POSTGRES_PASSWORD:?...}` from both the app and the database service; commit
  `ede8940`.
- Production follow-up: source secrets from a managed secret store instead of a file.
- How to verify: `grep -r POSTGRES_PASSWORD` shows only variable references, no literal
  values, in `docker-compose.yml`.

## Finding 3 — Old plaintext password still recoverable from git history
- Risk and evidence: `config/app.env` (with the real, though lab-only, password) was
  tracked in earlier commits before it was added to `.gitignore`.
- Impact: anyone with read access to the repository (or its history via a clone made
  before the fix) can recover the old credential even though the current tree no longer
  contains it.
- Implemented fix / commit: `git rm --cached config/app.env` stops tracking it going
  forward (commit `ede8940`); history itself was **not** rewritten (see decisions.md,
  Decision 3) — this is a known, disclosed, unresolved item.
- Production follow-up: rotate the credential immediately in any real incident, and
  perform a `git filter-repo`/BFG history rewrite in a coordinated maintenance window.
- How to verify: `git log --all --full-history -- config/app.env` still shows the
  earlier commits that contained it.

## Finding 4 — PostgreSQL and Redis ports were published to the host
- Risk and evidence: original `docker-compose.yml` published
  `127.0.0.1:15432:5432` and `127.0.0.1:16379:6379`.
- Impact: any process or user on the host (not just the app containers) could connect
  directly to the databases, bypassing the application entirely.
- Implemented fix / commit: removed both port mappings; Stage 5 fix commit.
- Production follow-up: in a multi-host deployment, also restrict database access at
  the security-group/firewall level, not just at the Compose/network level.
- How to verify: `validate.py`'s "no published PostgreSQL/Redis ports" check (PASS,
  commit `3601ad6`); `netstat -ano | findstr :15432` / `:16379` return nothing.

## Finding 5 — NGINX could reach the database network directly
- Risk and evidence: NGINX was originally attached to both `frontend` and `backend`
  networks, so a compromised/misconfigured NGINX could talk to PostgreSQL/Redis
  directly, bypassing the app layer entirely.
- Impact: defense-in-depth failure — the app's own authorization/validation logic
  could be bypassed if NGINX itself were ever compromised or misconfigured.
- Implemented fix / commit: NGINX now joins only `frontend`; `backend` is marked
  `internal: true`; Stage 5 fix commit.
- Production follow-up: enforce this at the orchestrator level too (e.g. Kubernetes
  NetworkPolicy), not only via Compose network membership.
- How to verify: `docker compose exec nginx nc -z -w2 postgres 5432` → `nc: bad
  address` (DNS-level unreachability); automated in `validate.py` (PASS).

## Finding 6 — Application logged the database password at startup
- Risk and evidence: while diagnosing Stage 2, `app-01`'s logs showed a
  `configuration_loaded` event that included the full `DATABASE_URL` (password
  included) in plaintext.
- Impact: the credential ends up in log storage/log aggregation systems, which
  typically have much broader read access than the secret store itself.
- Implemented fix / commit: **not implemented** — this is app-code behavior outside
  the Docker/NGINX scope of this assessment; logged here rather than left out.
- Production follow-up: redact credentials before logging (log a masked DSN, or log
  only the host/db name, never the full connection string).
- How to verify: reproduce by triggering a fresh `configuration_loaded` log line and
  inspecting it for the password substring.

## Finding 7 — Dependency failures are not diagnosable from application logs
- Risk and evidence: when PostgreSQL was unreachable (Stage 2), the app only logged
  `"status":"not_ready"` with no underlying error detail (no exception message, no
  error code) — extensive `findstr` searches for "error"/"password"/"traceback" in
  `app-01`'s logs found nothing.
- Impact: on-call debugging in production would have no log-based lead on *why* a
  dependency is down, only *that* it is down.
- Implemented fix / commit: **not implemented** — app-code change, out of this
  assessment's scope.
- Production follow-up: log the actual exception type/message (not necessarily the
  full connection string) when a dependency check fails.
- How to verify: reproduce a dependency failure and grep the resulting logs for
  exception detail — currently absent.

## Finding 8 — `restart: unless-stopped` did not reliably survive a full host reboot
- Risk and evidence: after the host machine was fully restarted, `app-02` and `nginx`
  stayed `Exited` while `app-01`/`postgres`/`redis` (identical restart policy) came
  back automatically — see `troubleshooting.md` Entry 8.
- Impact: an unattended host reboot (e.g. a patch cycle) could leave part of the stack
  down with no automatic recovery and no alert.
- Implemented fix / commit: manual recovery only (`docker compose up -d`); no code fix
  exists for this, since it's a platform-level reliability gap, not a config bug.
- Production follow-up: run under a real orchestrator (Kubernetes, ECS, etc.) with a
  reconciliation loop, rather than relying on `restart:` policies on a single Docker
  host; add host-level monitoring/alerting on container health.
- How to verify: reboot the host and check `docker compose ps -a` — do this outside
  the graded evidence window; already reproduced once for real (see Entry 8).

## Finding 9 — Single instance of PostgreSQL and Redis (no replication)
- Risk and evidence: exactly one PostgreSQL container and one Redis container back the
  whole stack; there is no replica, no automatic failover, and `failure_test.py` only
  exercises app-layer failover (app-01/app-02), never a database-layer failure.
- Impact: PostgreSQL or Redis going down is a full outage with no automatic recovery —
  a single point of failure the current design does not address.
- Implemented fix / commit: **not implemented** — out of scope for this assessment
  (single-host lab), documented as a known limitation rather than hidden.
- Production follow-up: managed/replicated PostgreSQL (e.g. a primary + standby, or a
  managed cloud database) and Redis Sentinel/Cluster for cache availability.
- How to verify: stop the `postgres` container and observe `/ready` fail with no
  automatic recovery path (not run here — would break the working environment
  unnecessarily before the video).