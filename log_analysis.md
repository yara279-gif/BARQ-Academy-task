# Log analysis

Use all three supplied logs. Answer every question with commands/scripts and actual output.

1. What UTC interval is covered? How many valid, malformed and duplicate lines are in each file?
2. How many distinct client requests occurred? How did you deduplicate and avoid counting retries twice?
3. What are the final client status counts and error rate? State your denominator.
4. Which paths, time windows and backends account for the failures?
5. What are the median and p95 client latencies? State the percentile method and units.
6. Which requests retried upstream? How many succeeded after retrying?
7. Build an incident timeline using evidence from access, error AND application logs.
8. Show one correlated failed request and one successful request. Include IDs and timestamps.
9. Which errors appear to be proxy/connectivity issues versus dependency/application issues? What proves it?
10. What do the logs not prove? What would you check next in a running environment?

---

## Commands / scripts

All analysis is done by `analysis/analyze_logs.py`, which reads `logs/` read-only.
The original log files were never modified (verified with `git status` — `logs/` shows no changes).

```bash
python analysis/analyze_logs.py | tee analysis/output.txt
```

The script:
- parses `access.log` and `application.log` as JSON Lines, counting lines that fail
  `json.loads()` as malformed rather than aborting;
- parses `error.log` as NGINX text with regular expressions for timestamp,
  `request_id` and `upstream`;
- deduplicates on `request_id`, keeping the first record per ID;
- computes percentiles by the nearest-rank method.

Spot-check commands used to verify the script's output independently:

```bash
# total access lines
wc -l logs/access.log

# status distribution, cross-checked against the script
grep -o '"status":[0-9]*' logs/access.log | sort | uniq -c

# upstream error count
grep -c "connect() failed" logs/error.log

# inspect the malformed lines that were excluded
python - <<'EOF'
import json
for name in ("logs/access.log", "logs/application.log"):
    for i, line in enumerate(open(name, encoding="utf-8"), 1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            print(name, "line", i, repr(line[:120]))
EOF
```

### Parse exclusions

| File | Lines | Valid | Malformed / unparsed | Excluded because |
|---|---|---|---|---|
| access.log | 726 | 725 | 1 | not valid JSON — [FILL: paste the line, e.g. truncated record] |
| application.log | 730 | 729 | 1 | not valid JSON — [FILL] |
| error.log | 68 | 67 | 1 | no leading NGINX timestamp — [FILL] |

Malformed lines are excluded from all counts. They are 1 line per file
(~0.14% of access.log), too few to change any conclusion below.

---

## Results

### Q1 — Coverage, valid, malformed, duplicate lines

**UTC interval covered:** `2026-08-20T11:00:00.015Z` to `2026-08-20T11:29:57.578Z`
— a single window of just under 30 minutes.

| File | Total lines | Valid | Malformed | Distinct request_id | IDs appearing >1× | Extra duplicate lines |
|---|---|---|---|---|---|---|
| access.log | 726 | 725 | 1 | 720 | 5 | 5 |
| application.log | 730 | 729 | 1 | 680 | 49 | 49 |
| error.log | 68 | 67 | 1 | n/a | n/a | n/a |

Duplicates are real and differ between the two files, which matters for Q2:
`access.log` repeats 5 IDs, `application.log` repeats 49. The application file
logs an extra record for the same `request_id` when a request produces a
dependency error (see Q9: 47 `dependency_error` events), so its line count is
higher than its distinct-request count.

### Q2 — Distinct client requests and deduplication

**Distinct client requests: 720.**

Deduplication method, and why it avoids double-counting:

1. **Cross-file double-counting.** Every client request is recorded twice —
   once by NGINX in `access.log` and again by the app in `application.log`.
   Verification: the number of `application.log` request IDs *not* present in
   `access.log` is **0**, i.e. the application file contains no requests the
   edge did not see. Summing the two files would therefore roughly double the
   true figure. `access.log` is used as the sole denominator because NGINX is
   the single client-facing edge; every client request passes through it exactly
   once regardless of how many backends it touches.
2. **Within-file duplicates.** Grouping by `request_id` and keeping the first
   record removes the 5 repeated IDs in `access.log`.
3. **Retries.** A retry is *not* a second client request. NGINX records all
   upstream attempts for one request on a single access line, as a
   comma-separated `upstream` value (e.g.
   `172.23.0.12:8080, 172.23.0.11:8080`). Because retries live inside one line
   rather than producing extra lines, counting access lines by distinct
   `request_id` already counts each client request once. Retries are analysed
   separately in Q6 by splitting that field, never by counting rows.

### Q3 — Final client status counts and error rate

**Denominator: 720 distinct client requests** (deduplicated `access.log`,
final status per request — i.e. the status NGINX ultimately returned to the
client, not the per-attempt `upstream_status`).

| Status | Count | Share |
|---|---|---|
| 200 | 615 | 85.42% |
| 404 | 10 | 1.39% |
| 502 | 40 | 5.56% |
| 503 | 47 | 6.53% |
| 504 | 8 | 1.11% |

- **5xx error rate: 95 / 720 = 13.19%**
- **4xx rate: 10 / 720 = 1.39%**
- Combined non-2xx: 105 / 720 = 14.58%

The distinction between the three 5xx codes is the core finding and is
developed in Q9: 502 and 504 are proxy-side, 503 is application-side.

### Q4 — Failing paths, time windows and backends

**By path** (5xx only, n=95):

| Path | Failures |
|---|---|
| /records | 26 |
| /counter | 26 |
| /ready | 23 |
| /health | 10 |
| / | 10 |

The three dependency-touching endpoints (`/records`, `/counter`, `/ready`)
account for 75 of 95 failures. `/health` and `/` fail only during the window
where a backend was refusing connections — they have no dependency of their own,
which is itself evidence for the two-phase reading in Q7.

**By time window:** failures are not spread evenly across the 30 minutes. They
occur in discrete clusters:

| Window (UTC) | Failures | Character |
|---|---|---|
| 11:05–11:09 | 40 | 8/min, sustained |
| 11:12–11:15 | 31 | 8/min, sustained |
| 11:20–11:21 | 16 | 8/min |
| 11:25–11:26 | 8 | 4/min |

Minutes 11:00–11:04, 11:10–11:11, 11:16–11:19, 11:22–11:24 and 11:27–11:29
are clean.

**By backend:** two upstreams serve traffic, `172.23.0.11:8080` (379 requests,
final attempt) and `172.23.0.12:8080` (341). Errors are heavily skewed:

| Upstream in error.log | Errors |
|---|---|
| 172.23.0.12:8080 (all paths) | 63 |
| 172.23.0.11:8080 (/records only) | 4 |

63 of 67 upstream errors name `172.23.0.12`, across every endpoint including
`/health` and `/`. The 4 errors against `172.23.0.11` hit only `/records`.
Correlating with `application.log`: `172.23.0.12` is the address of the
instance logged as `app-02` (see Q7 — `app-02` disappears from the application
log exactly during the 11:05–11:09 error burst).

### Q5 — Latency

- **Units: milliseconds.** `access.log` reports `request_time` in seconds;
  values are multiplied by 1000. (`application.log` reports `duration_ms`
  already in milliseconds — mixing the two without conversion would be a
  1000× error.)
- **Method: nearest-rank percentile** — sort ascending, take element at index
  `ceil(p/100 × N)`, 1-indexed. No interpolation.
- **Population:** the 720 deduplicated client requests, measured at the edge
  (`access.log`), so the figure is client-observed latency including proxy and
  retry time.

| Metric | Value |
|---|---|
| n | 720 |
| min | 3.0 ms |
| median (p50) | 54.0 ms |
| p95 | 2001.0 ms |
| max | 2025.0 ms |

The gap between p50 and p95 is the important part: the median request is fast
(54 ms), but the top 5% sit at roughly 2000 ms — a flat ceiling, not a gradual
tail. A hard clustering at ~2.0 s indicates a **timeout**, not gradual load:
requests are being cut off at a configured limit rather than slowing down
organically. This matches the 8 × 504 responses in Q3.

### Q6 — Upstream retries

**19 requests were retried** (identified by a comma-separated `upstream` value,
i.e. more than one attempt recorded for one client request).

- Succeeded after retry (final status < 400): **19**
- Still failed after retry: **0**

So every retry recovered. Worked example:

```
lab-000124
  upstream        = 172.23.0.12:8080, 172.23.0.11:8080
  upstream_status = 502, 200
  final status    = 200
```

The first attempt against `172.23.0.12` returned 502; NGINX retried the same
request against `172.23.0.11`, which returned 200, and the client saw 200.
This is why the client-facing error rate (13.19%) is *lower* than the raw
upstream failure count would suggest — retries absorbed 19 failures before they
reached the client. It is also why per-attempt `upstream_status` must not be
used as the denominator in Q3.

---

## Timeline and correlated examples

### Q7 — Incident timeline

Evidence is drawn from all three logs. `application.log`'s per-minute
`instance_id` distribution is the decisive signal: in normal minutes both
backends log ~12 requests each; when a backend is down it stops logging
entirely while the other absorbs the load.

| Time (UTC) | Evidence | Reading |
|---|---|---|
| 11:00–11:04 | application.log: `{app-01: 12, app-02: 12}` each minute. No error.log lines. Only 404s on `/missing`. | Healthy baseline. Traffic split evenly across both backends. |
| **11:05:02** | error.log first entry: `connect() failed (111: Connection refused)`, upstream `172.23.0.12:8080`. | **Incident 1 begins.** app-02 stops accepting TCP connections. |
| 11:05–11:08 | application.log: `{app-01: 16}` only — app-02 logs nothing. error.log: 12 lines/min. access.log: 8 × 5xx/min, spread across `/`, `/health`, `/ready`, `/records`, `/counter`. | app-02 is down, not merely erroring: it never receives the requests, so it cannot log them. app-01 absorbs all traffic (12 → 16/min). Some requests retry onto app-01 and succeed (Q6); the rest return 502. |
| 11:09 | application.log: `{app-01: 15, app-02: 1}`. error.log drops to 11 lines. | **Recovery of app-02** — it logs its first request again. |
| 11:10–11:11 | `{app-01: 12, app-02: 12}`. No errors. | Fully recovered. Load-balancing restored to even split. |
| **11:12–11:15** | error.log is **silent**. But access.log shows 8 × 5xx/min, and application.log shows both instances logging *more* than baseline (16/min each) with `level: ERROR`, `event: dependency_error`. | **Incident 2 begins — different failure mode.** Both backends are up and reachable (no proxy errors), receiving and logging requests, but failing internally. These are the 503s. |
| 11:16–11:19 | Clean. Both instances at 12/min, no ERROR events. | Dependency recovers briefly. |
| 11:20–11:21 | Same signature as 11:12–11:15: no error.log entries, both instances at 16/min, dependency errors in application.log. | Incident 2 recurs. |
| 11:22–11:24 | Clean. | Recovery. |
| **11:25–11:26** | error.log returns: 4 lines/min, this time including `timed out` against `172.23.0.11:8080/records`. access.log: 4 × 5xx/min, latency at ~2000 ms. | **Incident 3** — a third mode: not refusal but timeout. Requests to `/records` hang until the proxy read timeout fires, producing the 8 × 504 and the p95 ceiling from Q5. |
| 11:27–11:29 | Both instances at 12/min, no errors. | Environment stable at end of capture. |

**Summary:** three distinct failure modes in one 30-minute window, not one
continuous outage — (1) a backend process down and refusing connections
11:05–11:09, (2) a shared dependency failing while both backends stay up
11:12–11:15 and 11:20–11:21, and (3) slow/hanging requests hitting a proxy
timeout 11:25–11:26.

### Q8 — Correlated requests

**Successful request — `lab-000002`**

| Log | Evidence |
|---|---|
| access.log | `2026-08-20T11:00:02.532Z` `GET /health` status=200 upstream=`172.23.0.12:8080` upstream_status=200 request_time=0.032s |
| application.log | `2026-08-20T11:00:02.532Z` instance=`app-02` level=INFO status=200 duration_ms=32.0 |
| error.log | no entry |

Identical timestamp and `request_id` across both JSON logs, `upstream`
`172.23.0.12` maps to `instance_id` `app-02`, and the two durations agree
(0.032 s = 32.0 ms) — which is what establishes the join key and the
seconds/milliseconds unit relationship used throughout.

**Failed request — `[FILL: request_id from the corrected run]`**

| Log | Evidence |
|---|---|
| access.log | `[FILL timestamp]` `[FILL method/path]` status=`[FILL]` upstream=`[FILL]` upstream_status=`[FILL]` request_time=`[FILL]` |
| application.log | `[FILL — state explicitly whether a record exists. For an 11:05–11:09 connection-refused request, expect NO record; for an 11:12–11:15 503, expect an ERROR / dependency_error record]` |
| error.log | `[FILL timestamp]` `connect() failed (111: Connection refused)` upstream=`[FILL]` |

> Note: the first version of the parser did not capture `request_id` from
> `error.log` (a regex defect), which made this correlation come back empty and
> reported "0 requests with an upstream error and no application record".
> That was a tooling bug, not a finding. The parser was corrected and rerun;
> the figures above come from the corrected run. The failed attempt is recorded
> in `troubleshooting.md`.

---

## Conclusions and limits

### Q9 — Proxy/connectivity vs dependency/application errors

The two classes are separable because the three logs disagree in a specific,
informative way.

**Proxy / connectivity errors — 67 upstream errors in error.log**

| Reason | Count |
|---|---|
| connect() failed (111: Connection refused) | 59 |
| upstream timed out | 8 |

What proves it is connectivity rather than application logic:

- NGINX reports failure at the *connect* stage — it never established a TCP
  session, so no HTTP exchange occurred.
- The corresponding requests have **no matching record in `application.log`**
  ([FILL: count from corrected run]). A process that never received the request
  cannot log it. This absence is the strongest available evidence.
- During 11:05–11:09, `app-02` vanishes entirely from `application.log` while
  `app-01` keeps logging — consistent with one backend process being down, not
  with an application bug that would affect both.
- These map to the **502** (refused) and **504** (timed out) responses.

**Dependency / application errors — 47 events**

- `application.log` contains 47 entries at `level: ERROR` with
  `event: dependency_error`, against `/ready` (23), `/counter` (16) and
  `/records` (8).
- These occur in windows where `error.log` is **completely silent**
  (11:12–11:15, 11:20–11:21) — the proxy reached the backend without
  difficulty; the backend accepted the request, processed it, and failed.
- The affected paths are exactly the ones that touch PostgreSQL or Redis.
  `/health`, which touches neither, does not fail in these windows.
- These map to the **503** responses.

**In short:** absence of an application-log record proves connectivity;
presence of an application-log record with an ERROR level proves the request
arrived and the failure was internal. The event type distribution
(`http_request`: 682, `dependency_error`: 47) and level distribution
(INFO 625, WARN 57, ERROR 47) corroborate this split.

### Q10 — What the logs do not prove, and what to check next

**Not proven by these logs:**

1. **Why `app-02` stopped accepting connections at 11:05.** "Connection
   refused" establishes that nothing was listening on `172.23.0.12:8080`. It
   does not distinguish between a crashed process, an OOM kill, a container
   restart, a process that never bound the port, or a process bound to the
   wrong interface. No container lifecycle events appear in any of the three
   files.
2. **Which dependency failed, and how.** `event: dependency_error` names no
   dependency. Whether PostgreSQL, Redis or both were responsible — and whether
   the cause was connection exhaustion, authentication, disk, or a network
   partition — is not recoverable from this data.
3. **Causal direction between the incidents.** Whether the 11:12 dependency
   failures were triggered by the 11:05 backend outage, or are independent, is
   unknowable here.
4. **The mapping from IP to instance is inferred, not stated.** The association
   of `172.23.0.12` with `app-02` rests on correlating request IDs across
   files; the logs never assert it directly. Container IPs are reassignable,
   so this inference would not survive a restart.
5. **Whether traffic was evenly balanced by design.** The ~12/12 split is
   consistent with round-robin but is not proof of the configured method.
6. **Anything about the current environment.** The `logs/README.md` states these
   describe a *historical* incident. No conclusion about today's stack follows
   from them, and none is claimed here.
7. **Client-side impact.** The logs show status codes, not whether users
   retried, abandoned, or were affected in ways the edge did not record.

**What I would check next in a running environment:**

- `docker compose ps -a` and `docker inspect` on the app containers for exit
  codes, `OOMKilled`, and restart counts covering the incident window.
- `docker compose logs app-02` for stack traces or bind errors at 11:05, and
  whether the process bound `0.0.0.0` or only loopback.
- PostgreSQL and Redis server logs and connection counts for 11:12–11:15 and
  11:20–11:21, plus `max_connections` against the app's pool size.
- The NGINX `upstream` block: `proxy_connect_timeout` / `proxy_read_timeout`
  (to confirm the ~2000 ms ceiling in Q5), `proxy_next_upstream` settings that
  produced the 19 retries, and whether health-based ejection is configured.
- Resource limits and host memory pressure during the window.
- Whether `/ready` actually verifies both PostgreSQL and Redis, since it failed
  alongside `/counter` and `/records`.

**Limits of this analysis:** 3 malformed lines were excluded (1 per file,
~0.4% of total); counts are therefore lower bounds. The observation window is
a single 30-minute capture with no comparison period, so "normal" is defined
only by the clean minutes inside the same window. All conclusions are derived
from the script in `analysis/analyze_logs.py`; none were counted by hand.
