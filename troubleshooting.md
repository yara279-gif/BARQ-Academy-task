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
  INSTANCE_ID: "app-01" (copy-paste error).
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