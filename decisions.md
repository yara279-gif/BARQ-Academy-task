# Technical decisions

## Decision 1 — Base images: keep the pinned slim/alpine images as supplied
- Choice: kept `python:3.12-slim-bookworm`, `postgres:16-alpine`, `redis:7.4-alpine`,
  `nginx:1.28-alpine`, each pinned by SHA digest (not just a tag), instead of switching
  to full/default images.
- Why: slim/alpine images have a much smaller attack surface and footprint; pinning by
  digest means `docker compose build` always gets the exact same base, not whatever a
  mutable tag happens to point to today.
- Alternative: full Debian-based images (easier to `apt install` debugging tools into,
  but larger and more packages to keep patched).
- Trade-off: alpine's musl libc occasionally behaves differently from glibc for some
  Python wheels, and alpine images ship fewer debugging tools by default (had to rely on
  `nc`, which is present, rather than assuming e.g. `curl` is always there).
- Evidence / commit: unchanged from starter `docker-compose.yml`/`Dockerfile`; verified
  working through all of Part 2/3.
- Production improvement: add automated image/CVE scanning (e.g. Trivy) in CI to catch
  a base image that becomes vulnerable after the digest was pinned.

## Decision 2 — Single source of truth for secrets via a root `.env`
- Choice: removed the hardcoded `POSTGRES_PASSWORD` from `docker-compose.yml` and the
  separate copy in `config/app.env`; both now resolve from one root `.env`
  (`${POSTGRES_USER}`, `${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}`,
  `${POSTGRES_DB}`), with `DATABASE_URL`/`REDIS_URL` built from those same variables.
- Why: the original two-copies-of-one-secret design is exactly what caused the Stage 2
  bug (password drifted between `config/app.env` and `docker-compose.yml`). One source
  removes the class of bug, not just this instance of it.
- Alternative: a secrets manager (Docker secrets, Vault, cloud KMS) — correct for
  production, overkill for a local single-host lab assessment.
- Trade-off: `.env` is still a plaintext file on disk; anyone with filesystem access to
  the host can read the real password.
- Evidence / commit: `ede8940` (fix), `whoami`/`/srv/app.env` verification in
  `troubleshooting.md` Entry 7.
- Production improvement: inject secrets from a managed secrets store at deploy time
  instead of a file on the host.

## Decision 3 — Did not rewrite git history to remove the old committed password
- Choice: ran `git rm --cached config/app.env` to stop tracking the secret file going
  forward, but left the old plaintext password value in earlier commits rather than
  rewriting history with `git filter-repo`/BFG.
- Why: history rewriting requires a force-push and changes every downstream commit hash;
  doing that close to a hard deadline risks breaking the repo (or CI's view of it) with
  very little time to recover.
- Alternative: rewrite history now and force-push.
- Trade-off: the old (lab-only, disposable) password remains recoverable from git
  history indefinitely unless rewritten later.
- Evidence / commit: `git ls-files`/`git rm --cached` sequence, `ede8940`.
- Production improvement: in a real incident, rotate the credential immediately
  (assume it's compromised the moment it's in history) and schedule a history rewrite
  in a maintenance window with all collaborators notified.

## Decision 4 — PostgreSQL on a named volume, Redis with AOF persistence
- Choice: mounted PostgreSQL's data directory on a named Docker volume (not `tmpfs`,
  not the wrong path as originally shipped) and enabled Redis `--appendonly yes` backed
  by its own named volume.
- Why: the task requires data to survive container recreation; `tmpfs` is memory-backed
  and is wiped on every container restart by design.
- Alternative: bind-mount a host directory instead of a named volume — works, but ties
  the data to a specific host path and complicates permissions across OSes.
- Trade-off: named volumes are less convenient to browse directly from the host
  filesystem than a bind mount.
- Evidence / commit: `0ba9c6c`; real persistence proof in `troubleshooting.md` Entry 4
  and again via `backup.sh`/`restore.sh`'s destroy/restore test.
- Production improvement: point-in-time recovery (WAL archiving) and off-host backup
  storage, not just an on-demand `pg_dump`.

## Decision 5 — NGINX active + passive failover with health-gated startup
- Choice: added `max_fails`/`fail_timeout` (passive) and `proxy_next_upstream error
  timeout http_502 http_503` with `proxy_next_upstream_tries 2` (active) to the NGINX
  upstream block, plus `depends_on: condition: service_healthy` so NGINX only starts
  once both app instances report healthy.
- Why: without these, a single backend failure surfaces as client-visible errors
  instead of being absorbed by the other instance.
- Alternative: a dedicated load balancer/service mesh (e.g. Traefik, Envoy) with more
  sophisticated circuit-breaking — heavier than this assessment's scope.
- Trade-off: `proxy_next_upstream_tries 2` means a client request can take up to
  roughly double the single-backend timeout in the worst case (one failed attempt, then
  one successful retry) before it fails outright.
- Evidence / commit: `571134e`; real failover proof in `troubleshooting.md` Entry 6 and
  `failure_test.py` (6/6 checks passed, 20/20 requests succeeded via the surviving
  backend during the outage).
- Production improvement: externalize load balancing/failover to a managed layer (cloud
  load balancer or service mesh) that also handles TLS and slow-start.

## Decision 6 — Network segmentation: `frontend`/`backend`, `backend` marked internal
- Choice: NGINX only joins `frontend`; PostgreSQL and Redis are only reachable on
  `backend`, which is marked `internal: true` (no default route out, and unreachable
  from outside Docker); no PostgreSQL/Redis ports are published to the host.
- Why: the task requires that only NGINX be reachable on the host, and that NGINX
  itself cannot reach the databases directly — defense in depth in case NGINX is ever
  compromised.
- Alternative: a single flat network for all five services (simpler compose file, but
  no real isolation).
- Trade-off: debugging from the host requires going through `docker compose exec`
  rather than connecting directly to Postgres/Redis with a local client on a published
  port.
- Evidence / commit: Stage 5 fix commit; real isolation proof (`nc` → `bad address`
  from inside the `nginx` container) automated into `validate.py`'s
  `nginx cannot reach postgres/redis` and `no published PostgreSQL/Redis ports` checks
  (12/12 passing, commit `3601ad6`).
- Production improvement: network policies enforced at the orchestrator level
  (Kubernetes NetworkPolicy) rather than relying solely on Compose network topology.