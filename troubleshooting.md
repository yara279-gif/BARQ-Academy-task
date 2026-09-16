# Troubleshooting journal

Keep chronological entries. Copy this block for each meaningful investigation.

<!-- ## Entry / date / time
- Symptom:
- Hypothesis:
- Command or test:
- Actual output:
- Failed attempt and what changed your thinking:
- Root cause:
- Fix:
- Retest evidence:
- Related commit:
- Remaining uncertainty:

Do not fabricate a failed attempt just to fill the template. Record actual attempts. -->

## Entry 1 / 2026-09-14
- Symptom: GET /health via NGINX returned 502 Bad Gateway, then curl showed
  "Server: Apache" instead of nginx before that
- Hypothesis: multiple misconfigurations in the request path (nginx upstream
  port, app bind address, published port) plus local environment conflicts.
- Command or test: docker compose up -d --force-recreate
- Actual output: Error response from daemon: Conflict. The container name
  "/redis" is already in use by container e6778275b518...
- Failed attempt and what changed your thinking: tried to remove the
  conflicting container outright, but it belonged to another project (in my device)
  with data I still need — renamed it instead with
  `docker rename redis crm-redis`, which freed the name without losing data.
- Command or test: docker compose up -d (after rename)
- Actual output: nginx failed to start — "Error response from daemon: Ports
  are not available: exposing port TCP 127.0.0.1:8080 ... bind: An attempt
  was made to access a socket in a way forbidden by its access permissions."
- Command or test: netstat -ano | findstr :8080 -> PID 5412
  tasklist /FI "PID eq 5412" -> httpd.exe (Apache, from local XAMPP)
- Failed attempt and what changed your thinking: `taskkill /PID 5412 /F`
  from a normal terminal did nothing (Apache runs as a Windows service);
  running the same command from an Administrator terminal worked.
   Command or test: curl.exe -i http://127.0.0.1:8080/health (after Apache
  killed and nginx restarted)
- Actual output: HTTP/1.1 502 Bad Gateway, Server: nginx/1.28.3
  docker compose logs nginx showed:
  connect() failed (111: Connection refused) ... upstream:
  "http://172.19.0.3:8081/health"
- Root cause: three separate issues stacked on top of each other:
  (1) nginx.conf pointed to app-01:8081 instead of the app's real port 8080
  (2) app containers were bound to APP_HOST=127.0.0.1 (loopback only,
      unreachable from nginx's container)
  (3) nginx's published port was mapped to container port 81, not 80
  Plus two local-machine blockers unrelated to the repo: a stray "redis"
  container name conflict, and XAMPP's Apache already holding host port 8080.
- Fix: nginx.conf server line -> app-01:8080; docker-compose.yml
  APP_HOST -> "0.0.0.0"; nginx ports mapping -> ":80". Also learned that
  nginx caches its config at container start 

## Entry 2 / 2026-09-14
- Symptom: /ready returned {"postgres":"unavailable","redis":"ready"} even
  after fixing the nginx/bind issues in Entry 1.
- Hypothesis: config/app.env has wrong ports for postgres/redis.
- Command or test: docker compose logs app-01 | findstr /I "postgres error dependency"
- Actual output: only showed "configuration_loaded" with
  database_url=postgresql://barq_app:BarqLabOnly_7qN2vK8d@postgres:5432/barq_tasks
  -- the app does not log the actual connection failure reason at all.
- Failed attempt and what changed your thinking: searched logs for
  "password fatal traceback authentication" -- no match. Confirmed the app
  swallows dependency errors silently; had to diagnose by comparing the
  config file values directly instead of trusting the logs.
- Root cause: two separate mismatches in config/app.env:
  (1) ports (postgres:5433, redis:6380) did not match the running services
      (5432, 6379)
  (2) DATABASE_URL password (...7qN2vK8d) did not match
      POSTGRES_PASSWORD in docker-compose.yml (...7qN2vK8c)
- Fix: corrected both port numbers and the password's last character.
- Retest evidence: curl http://127.0.0.1:8080/ready ->
  {"dependencies":{"postgres":"ready","redis":"ready"},...,"status":"ready"}
  curl http://127.0.0.1:8080/counter -> {"counter":1,...}
  curl http://127.0.0.1:8080/records -> 2 seeded records listed
- Related commit: fc955c5
- Remaining uncertainty: the app never logs *why* a dependency is
  unavailable -- worth flagging in security_review.md as a
  diagnosability/logging gap.


## Entry 3 / 2026-09-14
- Symptom: docker compose ps showed "health: starting"/unhealthy previously;
  /instance always returned app-01 even after both containers were healthy.
- Hypothesis: healthcheck probe hitting wrong path, and/or app-02 misconfigured
  with the same identity as app-01.
- Command or test: read docker-compose.yml x-app healthcheck block and app-02
  environment block directly.
- Actual output: healthcheck test URL was '.../healthz' (app only serves
  '/health' per APPLICATION.md); app-02's environment had
  INSTANCE_ID: "app-01".
- Root cause: healthcheck path typo, and app-02 never got its own instance id.
- Fix: healthcheck path -> /health; app-02 INSTANCE_ID -> "app-02".
- Retest evidence: docker compose ps -> both app-01 and app-02 (healthy).
  8 rapid /instance calls right after recreate all returned app-01; a second
  round of 13 calls spaced ~2s apart alternated correctly between app-01 and
  app-02 (nginx access log confirmed different upstream IPs per request).
- Related commit: 96f57277a792d4232bb72058d653f150dcc75328
- Remaining uncertainty: why the first burst of requests immediately after
  --force-recreate all landed on app-01 -- possibly nginx's round-robin
  state or app-02's connection warm-up right after container start. Did not
  investigate further; noting it as a transient startup behavior, not a
  functional bug, since load balancing works correctly once traffic is spaced out.

## Entry 4 / 2026-09-14
- Symptom: needed to prove PostgreSQL data survives container recreation
  before trusting the persistence setup.
- Hypothesis: docker-compose.yml volume mount and Redis persistence flags
  looked misconfigured on inspection.
- Command or test: read docker-compose.yml postgres/redis service blocks
  directly.
- Actual output: postgres had `tmpfs: [/var/lib/postgresql/data]` (a RAM
  disk) shadowing the real data directory, while the named volume
  `postgres-data` was mounted at the wrong path
  (/var/lib/postgresql/backup, which Postgres never writes to). Redis had
  `--save "" --appendonly no`, disabling all persistence, with no volume
  attached at all.
- Root cause: two-part misconfiguration on postgres (tmpfs shadowing +
  wrong volume path), plus Redis persistence disabled outright.
- Fix: removed the tmpfs line; remounted postgres-data at
  /var/lib/postgresql/data; enabled Redis --appendonly yes with its own
  redis-data volume.
- Retest evidence:
    POST /records {"title":"Persistence proof"} -> id 3 created
    GET /records -> id 3 present
    docker compose down (no -v, volumes kept)
    docker compose up -d
    GET /records -> id 3 STILL present alongside the original 2 seeded rows
- Related commit:  0ba9c6cc2fd7e99fb58ec73cc5719abb2f6cf8e2
- Remaining uncertainty: none for this specific test; a real production
  concern (noted separately in security_review.md/decisions.md) is that
  this only proves survival across a clean `down`/`up`, not a crash or
  a `down -v` mistake by an operator.

## Entry 5 / 2026-09-14
- Symptom: needed to confirm NGINX cannot reach the databases directly, and
  that no database ports are exposed on the host.
- Hypothesis: docker-compose.yml had nginx on both frontend and backend
  networks, and postgres/redis both published host ports.
- Command or test: read docker-compose.yml network/ports sections directly.
- Actual output: nginx networks: [frontend, backend]; postgres
  ports: ["127.0.0.1:15432:5432"]; redis ports: ["127.0.0.1:16379:6379"].
- Root cause: over-broad network membership for nginx, and unnecessary
  host port publishing for the data tier.
- Fix: nginx networks -> [frontend] only; removed both ports: entries.
- Retest evidence:
    docker compose exec nginx sh -c "nc -z -w2 postgres 5432" -> "nc: bad
    address 'postgres'", exit=1
    docker compose exec nginx sh -c "nc -z -w2 redis 6379" -> "nc: bad
    address 'redis'", exit=1
    curl /ready -> still {"postgres":"ready","redis":"ready"} (apps retain
    backend access)
    netstat -ano | findstr ":15432 :16379" -> no output (ports not exposed)
- Related commit:cc7a89fcf4d4e301264ac79701c9f9e9e80bc015 
- Remaining uncertainty: none.

## Entry 6 / 2026-09-14
- Symptom: needed to confirm that stopping one backend does not take down
  the whole service.
- Hypothesis: nginx.conf had max_fails=0 (disables passive health checking)
  and proxy_next_upstream off (disables retry to the other backend); compose
  had restart: "no" everywhere and no resource limits or health-gated
  startup ordering.
- Command or test: read nginx.conf upstream/location blocks and
  docker-compose.yml restart/depends_on sections directly.
- Actual output: confirmed max_fails=0, proxy_next_upstream off, restart:
  "no" on x-app, no depends_on conditions anywhere except a plain
  (unconditioned) nginx depends_on on the two apps.
- Root cause: no failover path configured, and no startup ordering
  guarantee that dependencies were actually ready before apps/nginx started.
- Fix: max_fails=3 fail_timeout=10s; proxy_next_upstream error timeout
  http_502 http_503 with proxy_next_upstream_tries 2; restart:
  unless-stopped everywhere; mem_limit/cpus per service; depends_on with
  condition: service_healthy (apps wait for postgres+redis, nginx waits
  for both apps).
- Retest evidence:
    docker compose stop app-01 -> 10/10 /instance requests still succeeded,
    all served by app-02
    docker compose start app-01 -> both healthy again within ~30s; 10
    subsequent requests alternated correctly between app-01 and app-02
- Related commit: 571134e8f933ff751947c445181a77aed10324ff
- Remaining uncertainty: none for this test; single points of failure that
  remain (postgres/redis each have only one instance) are a production-plan
  item, not something fixed here -- will note in decisions.md/security_review.md.

## Entry 7 — Container running as root and secret baked into image

**Symptom:** No functional/runtime symptom. Found during a security review of
`Dockerfile` and `docker-compose.yml`, not from an incident in the running stack.

**Observation (before fix):**
- `Dockerfile` copied `config/app.env` into the image (`COPY config/app.env /srv/app.env`)
  and switched to `USER root` right before `CMD`, so the running container had
  both a copy of the database password baked into the image layer and full
  root privileges.
- `docker-compose.yml` hardcoded `POSTGRES_PASSWORD` in plaintext in the
  `postgres:` service, while `config/app.env` held a second, independently
  maintained copy of the same credential for the app services — the same
  "two copies of one secret can drift apart" pattern that caused the
  Stage 2 password mismatch.
- `config/app.env` (with the real password) was already tracked in git
  history from earlier commits.

**Fix:**
- `Dockerfile`: removed the `COPY config/app.env /srv/app.env` line and
  changed `USER root` → `USER app`.
- `docker-compose.yml`: removed `env_file: ./config/app.env` from the
  `x-app` anchor; `postgres:` and `x-app` environment blocks now read
  `${POSTGRES_USER}`, `${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}`,
  `${POSTGRES_DB}` from a single root-level `.env` file (gitignored);
  `DATABASE_URL`/`REDIS_URL` are built from those same variables instead of
  being duplicated.
- Added `.env.example` (root) and `config/app.env.example` as safe,
  committed templates.
- Ran `git rm --cached config/app.env` to stop tracking the file going
  forward, since adding it to `.gitignore` alone does not retroactively
  untrack an already-tracked file.

**Failed attempt / environment noise:** during `docker compose up -d` after
the rebuild, nginx failed to start with
`bind: An attempt was made to access a socket in a way forbidden by its
access permissions` on port 8080. `netstat -ano | findstr :8080` showed a
listener on `0.0.0.0:8080` (PID 5820); `tasklist /FI "PID eq 5820"` identified
it as `httpd.exe` (XAMPP Apache) — the same unrelated local-machine conflict
as Stage 1, just a new PID after a restart. Fixed by killing it from an
Administrator prompt (`taskkill /PID 5820 /F`), unrelated to the actual
security fix.

**Retest evidence:**

docker compose exec app-01 whoami
→ app

docker compose exec app-01 sh -c "ls /srv/app.env 2>&1"
→ ls: cannot access '/srv/app.env': No such file or directory

curl http://127.0.0.1:8080/ready
→ {"dependencies":{"postgres":"ready","redis":"ready"}, ...}

curl http://127.0.0.1:8080/records
→ records intact (no data loss from rebuild)


**Related commit:** `ede8940` — security: run app as non-root, stop baking
secrets into image, source credentials from .env

**Remaining uncertainty / known limitation:** the plaintext password value
still exists in earlier git commit history (before this fix). Fully removing
it would require rewriting git history (`git filter-repo` / BFG), which was
not done here due to the risk of a forced history rewrite this close to the
deadline. This is logged as an open finding in `security_review.md` rather
than silently left out.


## Entry 8 — Containers did not all come back after a full host restart

**Symptom:** After the machine was restarted, `docker compose ps` showed only
`app-01`, `postgres` and `redis` as `Up (healthy)`. `app-02` and `nginx` were
missing from the default `ps` output entirely.

**Command / test:**

docker compose ps -a

**Actual output:** `app-02` — `Exited (143) 22 hours ago`; `nginx` — `Exited (0)
22 hours ago`. Both carry `restart: unless-stopped`, same as `app-01`, `postgres`
and `redis`, which did come back automatically.

**Failed attempt / what changed thinking:** Initially assumed `restart:
unless-stopped` guarantees every container returns after any host reboot. The
uneven result (3 of 5 came back, 2 didn't) showed that assumption doesn't hold
reliably across a full Docker Desktop / host restart on this machine.

**Contributing factor:** port 8080 was re-occupied by XAMPP's `httpd.exe`
(same conflict as Stage 1/Stage 7, new PID) after the reboot, which would at
minimum have blocked `nginx` from rebinding even if Docker attempted to
restart it.

**Fix (this session):** killed the process holding port 8080
(`taskkill /PID <pid> /F` from an Administrator prompt), then
`docker compose up -d`, which brought `app-02` and `nginx` back to `healthy`
within seconds — no data loss, no rebuild needed.

**Retest evidence:**

docker compose ps
→ all 5 containers Up (healthy), nginx shows 127.0.0.1:8080->80/tcp

python failure_test.py
→ 6/6 checks passed


**Related commit:** none (operational recovery, not a code fix) — logged here
and in `security_review.md` as a production-readiness finding.

**Remaining uncertainty:** unclear whether `app-02`/`nginx` failed to restart
purely because of the port conflict, or because Docker Desktop's restart-policy
handling across a full host reboot is itself unreliable for locally-built
images. In production this would be mitigated by an orchestrator (e.g.
Kubernetes) rather than relying on `restart: unless-stopped` alone.