
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

LOGS = Path(__file__).resolve().parent.parent / "logs"

# ---------------------------------------------------------------- helpers

def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_jsonl(path):

    records, malformed, total = [], [], 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                malformed.append((lineno, line[:160]))
    return records, malformed, total


def load_error_log(path):

    errors, unparsed, total = [], [], 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line.strip():
                continue
            total += 1
            ts = re.match(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})", line)
            if not ts:
                unparsed.append((lineno, line[:160]))
                continue
            rid = re.search(r"request_id=([\w-]+)", line)
            ups = re.search(r'upstream: "([^"]*)"', line)
            lvl = re.search(r"\[(\w+)\]", line)
            low = line.lower()
            if "connection refused" in low:
                reason = "connection refused"
            elif "timed out" in low:
                reason = "timeout"
            elif "no live upstreams" in low:
                reason = "no live upstreams"
            else:
                reason = "other"
            errors.append({
                "ts": ts.group(1),
                "level": lvl.group(1) if lvl else None,
                "rid": rid.group(1) if rid else None,
                "upstream": ups.group(1) if ups else "",
                "reason": reason,
                "raw": line,
            })
    return errors, unparsed, total


def percentile(sorted_vals, pct):
    """Nearest-rank percentile: index = ceil(pct/100 * N), 1-indexed."""
    if not sorted_vals:
        return None
    k = max(1, math.ceil(pct / 100 * len(sorted_vals)))
    return sorted_vals[k - 1]


def head(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


# ---------------------------------------------------------------- load

access, access_bad, access_total = load_jsonl(LOGS / "access.log")
appl,   appl_bad,   appl_total   = load_jsonl(LOGS / "application.log")
errors, err_bad,    err_total    = load_error_log(LOGS / "error.log")

# first record per request_id - deduplication for client-facing counts
first_by_id = {}
for r in access:
    rid = r.get("request_id")
    if rid and rid not in first_by_id:
        first_by_id[rid] = r

app_by_id = {}
for r in appl:
    rid = r.get("request_id")
    if rid and rid not in app_by_id:
        app_by_id[rid] = r

err_by_id = {e["rid"]: e for e in errors if e.get("rid")}

# ---------------------------------------------------------------- Q1

head("Q1  COVERAGE, VALID / MALFORMED / DUPLICATE LINES")

acc_ids = Counter(r["request_id"] for r in access if r.get("request_id"))
app_ids = Counter(r["request_id"] for r in appl if r.get("request_id"))

all_ts = [parse_ts(r["timestamp"]) for r in access if r.get("timestamp")]
if all_ts:
    print(f"UTC interval (access.log): {min(all_ts).isoformat()}"
          f"  ->  {max(all_ts).isoformat()}")
    span = (max(all_ts) - min(all_ts)).total_seconds()
    print(f"Span: {span:.0f} s ({span/60:.1f} min)")

print()
print(f"{'file':<20}{'lines':>8}{'valid':>8}{'malformed':>11}"
      f"{'distinct id':>13}{'dup ids':>9}{'extra dup lines':>17}")
for name, recs, bad, total, ids in (
        ("access.log", access, access_bad, access_total, acc_ids),
        ("application.log", appl, appl_bad, appl_total, app_ids),
):
    dup_ids = sum(1 for v in ids.values() if v > 1)
    dup_lines = sum(v - 1 for v in ids.values() if v > 1)
    print(f"{name:<20}{total:>8}{len(recs):>8}{len(bad):>11}"
          f"{len(ids):>13}{dup_ids:>9}{dup_lines:>17}")
print(f"{'error.log':<20}{err_total:>8}{len(errors):>8}{len(err_bad):>11}"
      f"{'n/a':>13}{'n/a':>9}{'n/a':>17}")

print("\nExcluded lines (quote these in log_analysis.md):")
for label, bad in (("access.log", access_bad),
                   ("application.log", appl_bad),
                   ("error.log", err_bad)):
    for lineno, text in bad:
        print(f"  {label} line {lineno}: {text!r}")
if not (access_bad or appl_bad or err_bad):
    print("  (none)")

# ---------------------------------------------------------------- Q2

head("Q2  DISTINCT CLIENT REQUESTS / DEDUPLICATION")
distinct = len(first_by_id)
print("Denominator = distinct request_id in access.log.")
print("NGINX is the single client-facing edge, so each client request crosses")
print("it exactly once. application.log records the SAME requests again;")
print("summing both files would double-count.")
print(f"\nDistinct client requests              = {distinct}")
print(f"application.log ids NOT in access.log = {len(set(app_ids) - set(acc_ids))}")
print(f"access.log ids NOT in application.log = {len(set(acc_ids) - set(app_ids))}")
print("\nRetries do not create extra access lines: all upstream attempts for one")
print("request share a line, as a comma-separated 'upstream' value (see Q6).")

# ---------------------------------------------------------------- Q3

head("Q3  FINAL CLIENT STATUS COUNTS AND ERROR RATE")
status_counts = Counter(r.get("status") for r in first_by_id.values())
for s, n in sorted(status_counts.items(), key=lambda x: str(x[0])):
    print(f"  {s}: {n:>5}   ({n/distinct*100:5.2f}%)")
errs5 = sum(n for s, n in status_counts.items()
            if isinstance(s, int) and 500 <= s < 600)
errs4 = sum(n for s, n in status_counts.items()
            if isinstance(s, int) and 400 <= s < 500)
print(f"\nDenominator = {distinct} distinct client requests (final status,")
print("not per-attempt upstream_status)")
print(f"5xx rate = {errs5}/{distinct} = {errs5/distinct*100:.2f}%")
print(f"4xx rate = {errs4}/{distinct} = {errs4/distinct*100:.2f}%")

# ---------------------------------------------------------------- Q4

head("Q4  FAILING PATHS / TIME WINDOWS / BACKENDS")
fail = [r for r in first_by_id.values()
        if isinstance(r.get("status"), int) and r["status"] >= 500]

print(f"5xx failures: {len(fail)}\n")
print("By path:")
for p, n in Counter(r.get("path") for r in fail).most_common():
    print(f"  {str(p):<12} {n}")

print("\nBy path and status:")
combo = Counter((r.get("path"), r.get("status")) for r in fail)
for (p, s), n in sorted(combo.items(), key=lambda x: (-x[1], str(x[0]))):
    print(f"  {str(p):<12} {s}  {n}")

print("\nFailures by minute (UTC):")
by_min = Counter(parse_ts(r["timestamp"]).strftime("%H:%M") for r in fail)
for t in sorted(by_min):
    print(f"  {t}  {'#' * min(by_min[t], 60)} {by_min[t]}")

print("\nAll requests by minute (UTC), for comparison:")
all_min = Counter(parse_ts(r["timestamp"]).strftime("%H:%M")
                  for r in first_by_id.values())
for t in sorted(all_min):
    f = by_min.get(t, 0)
    print(f"  {t}  total={all_min[t]:>3}  5xx={f:>3}"
          f"{'   <-- degraded' if f else ''}")

print("\nUpstream actually serving (last attempt on each request):")
for u, n in Counter(str(r.get("upstream", "")).split(",")[-1].strip()
                    for r in first_by_id.values()).most_common():
    print(f"  {u}: {n}")

print("\nerror.log upstreams:")
for u, n in Counter(e["upstream"] for e in errors).most_common():
    print(f"  {u}: {n}")

print("\nerror.log errors by upstream host:")
for u, n in Counter(re.sub(r"^https?://", "", e["upstream"]).split("/")[0]
                    for e in errors).most_common():
    print(f"  {u}: {n}")

# ---------------------------------------------------------------- Q5

head("Q5  LATENCY (median / p95)")
lat = sorted(float(r["request_time"]) * 1000
             for r in first_by_id.values() if r.get("request_time") is not None)
print("Source: access.log request_time (seconds) x 1000 -> milliseconds.")
print("application.log duration_ms is ALREADY milliseconds; mixing the two")
print("without conversion would be a 1000x error.")
print("Method: nearest-rank percentile, index = ceil(p/100 * N), no interpolation.")
print(f"\nn      = {len(lat)}")
if lat:
    print(f"min    = {lat[0]:.1f} ms")
    print(f"p50    = {percentile(lat, 50):.1f} ms")
    print(f"p90    = {percentile(lat, 90):.1f} ms")
    print(f"p95    = {percentile(lat, 95):.1f} ms")
    print(f"p99    = {percentile(lat, 99):.1f} ms")
    print(f"max    = {lat[-1]:.1f} ms")
    slow = [v for v in lat if v >= 1900]
    print(f"\nrequests >= 1900 ms: {len(slow)}  "
          f"(a flat ceiling here indicates a timeout, not gradual slowdown)")

# ---------------------------------------------------------------- Q6

head("Q6  UPSTREAM RETRIES")
retried = [r for r in first_by_id.values() if "," in str(r.get("upstream", ""))]
recovered = [r for r in retried
             if isinstance(r.get("status"), int) and r["status"] < 400]
print(f"Requests with more than one upstream attempt = {len(retried)}")
print(f"  succeeded after retry (final < 400)        = {len(recovered)}")
print(f"  still failed after retry                   = {len(retried) - len(recovered)}")
print("\nExamples:")
for r in retried[:5]:
    print(f"  {r['request_id']}  path={str(r.get('path')):<10} "
          f"upstream={r.get('upstream')}  "
          f"upstream_status={r.get('upstream_status')}  final={r.get('status')}")
print("\nRetries absorbed failures before they reached the client, which is why")
print("the client-facing error rate is lower than the raw upstream failure count.")

# ---------------------------------------------------------------- Q7

head("Q7  INCIDENT TIMELINE (three-log evidence)")
if errors:
    def ets(e):
        return datetime.strptime(e["ts"], "%Y/%m/%d %H:%M:%S")
    e_sorted = sorted(errors, key=ets)
    print(f"first upstream error : {e_sorted[0]['ts']}  ({e_sorted[0]['reason']})")
    print(f"last  upstream error : {e_sorted[-1]['ts']}  ({e_sorted[-1]['reason']})")
    print(f"total upstream errors: {len(errors)}")
    print("\nerror.log lines by minute:")
    for t, n in sorted(Counter(e["ts"][11:16] for e in errors).items()):
        print(f"  {t}  {'#' * min(n, 60)} {n}")
    print("\nerror.log reason by minute:")
    rmin = defaultdict(Counter)
    for e in errors:
        rmin[e["ts"][11:16]][e["reason"]] += 1
    for t in sorted(rmin):
        print(f"  {t}  {dict(rmin[t])}")

print("\napplication.log instance_id per minute (a backend that is DOWN stops")
print("logging entirely; a backend that is UP but failing keeps logging):")
inst_min = defaultdict(Counter)
for r in appl:
    if r.get("timestamp") and r.get("instance_id"):
        inst_min[parse_ts(r["timestamp"]).strftime("%H:%M")][r["instance_id"]] += 1
for t in sorted(inst_min):
    print(f"  {t}  {dict(inst_min[t])}")

print("\napplication.log ERROR / dependency_error events per minute:")
dep_min = Counter()
for r in appl:
    if r.get("event") == "dependency_error" or r.get("level") == "ERROR":
        if r.get("timestamp"):
            dep_min[parse_ts(r["timestamp"]).strftime("%H:%M")] += 1
for t in sorted(dep_min):
    print(f"  {t}  {'#' * min(dep_min[t], 60)} {dep_min[t]}")

print("\nCombined per-minute view (the key correlation):")
print(f"  {'min':<7}{'5xx':>5}{'nginx err':>11}{'app dep err':>13}   reading")
err_min = Counter(e["ts"][11:16] for e in errors)
for t in sorted(all_min):
    a = by_min.get(t, 0)
    b = err_min.get(t, 0)
    c = dep_min.get(t, 0)
    if a == 0:
        note = "clean"
    elif b and not c:
        note = "PROXY/CONNECTIVITY (backend unreachable)"
    elif c and not b:
        note = "DEPENDENCY (backend up, failing internally)"
    else:
        note = "mixed"
    print(f"  {t:<7}{a:>5}{b:>11}{c:>13}   {note}")

# ---------------------------------------------------------------- Q8

head("Q8  CORRELATED EXAMPLES")

def show(rid, label):
    print(f"\n--- {label}: {rid} ---")
    a = first_by_id.get(rid)
    if a:
        print(f"  access      : {a['timestamp']} {a.get('method')} {a.get('path')} "
              f"status={a.get('status')} upstream={a.get('upstream')} "
              f"upstream_status={a.get('upstream_status')} "
              f"request_time={a.get('request_time')}s")
    else:
        print("  access      : NO RECORD")
    p = app_by_id.get(rid)
    if p:
        print(f"  application : {p['timestamp']} instance={p.get('instance_id')} "
              f"level={p.get('level')} event={p.get('event')} "
              f"status={p.get('status')} duration_ms={p.get('duration_ms')}")
    else:
        print("  application : NO RECORD  <-- request never reached any app instance")
    e = err_by_id.get(rid)
    if e:
        print(f"  error       : {e['ts']} reason={e['reason']} upstream={e['upstream']}")
        print(f"                {e['raw'][:150]}")
    else:
        print("  error       : none")

# a failed request that produced an NGINX upstream error (connectivity class)
conn_fail = next((rid for rid in err_by_id
                  if rid in first_by_id and rid not in app_by_id), None)
if conn_fail is None:
    conn_fail = next((rid for rid in err_by_id if rid in first_by_id), None)
if conn_fail:
    show(conn_fail, "FAILED - connectivity class")

# a failed request the app itself logged as a dependency error
dep_fail = next((r.get("request_id") for r in appl
                 if r.get("event") == "dependency_error"
                 and r.get("request_id") in first_by_id), None)
if dep_fail:
    show(dep_fail, "FAILED - dependency class")

ok = next((r["request_id"] for r in first_by_id.values()
           if r.get("status") == 200), None)
if ok:
    show(ok, "SUCCESSFUL")

# ---------------------------------------------------------------- Q9

head("Q9  PROXY/CONNECTIVITY vs DEPENDENCY/APPLICATION")
print("error.log reasons:")
for r, n in Counter(e["reason"] for e in errors).most_common():
    print(f"  {r}: {n}")

with_err = set(err_by_id) & set(first_by_id)
no_app = [rid for rid in with_err if rid not in app_by_id]
print(f"\nrequest_ids captured from error.log        : {len(err_by_id)}")
print(f"  of those, present in access.log          : {len(with_err)}")
print(f"  of those, with NO application.log record : {len(no_app)}")
print("  -> the backend never accepted the connection, so the app could not")
print("     log the request. Absence of an app record IS the evidence.")
if no_app:
    print(f"  sample ids: {sorted(no_app)[:5]}")

app_err = [r for r in appl if r.get("event") == "dependency_error"]
print(f"\napplication.log dependency_error events     : {len(app_err)}")
if app_err:
    print("  by path:", dict(Counter(r.get("path") for r in app_err).most_common()))
    dep_ids = {r.get("request_id") for r in app_err}
    print(f"  of those, ALSO in error.log              : {len(dep_ids & set(err_by_id))}")
    print("  -> the request arrived and was processed; the failure was internal.")
    print("     Near-zero overlap with error.log is what separates the classes.")

print(f"\napplication.log level counts: "
      f"{dict(Counter(r.get('level') for r in appl))}")
print(f"application.log event counts: "
      f"{dict(Counter(r.get('event') for r in appl))}")

print("\nStatus code mapping:")
print("  502 / 504  -> proxy could not reach or was not answered by the backend")
print("  503        -> backend answered, but a dependency failed")
print()
