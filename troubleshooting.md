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
