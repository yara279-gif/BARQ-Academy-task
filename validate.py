
import sys
import json
import time
import subprocess
import argparse
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:8080"
RESULTS = []


def record(name, passed, detail=""):
    RESULTS.append((name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


def http_get(path, timeout=3):
    req = urllib.request.Request(BASE_URL + path, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8")


def http_post(path, payload, timeout=3):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8")


def check_public_access():
    try:
        status, _ = http_get("/health")
        record("public access on published port", status == 200, f"status={status}")
    except Exception as e:
        record("public access on published port", False, str(e))


def wait_for_ready(max_attempts=20, delay=1.5):
    """Bounded wait: retry /ready instead of failing instantly or hanging forever."""
    last_error = "never got a response"
    for attempt in range(1, max_attempts + 1):
        try:
            status, body = http_get("/ready")
            data = json.loads(body)
            deps = data.get("dependencies", {})
            if status == 200 and deps.get("postgres") == "ready" and deps.get("redis") == "ready":
                record("readiness (postgres + redis)", True, f"ready after {attempt} attempt(s)")
                return True
            last_error = f"attempt {attempt}: {body}"
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            last_error = f"attempt {attempt}: {e}"
        time.sleep(delay)
    record("readiness (postgres + redis)", False, last_error)
    return False


def check_endpoint(path):
    try:
        status, _ = http_get(path)
        record(f"endpoint {path}", status == 200, f"status={status}")
    except Exception as e:
        record(f"endpoint {path}", False, str(e))


def check_records():
    try:
        status, _ = http_post("/records", {"title": "validate.py check"})
        if status not in (200, 201):
            record("POST /records", False, f"status={status}")
            return
        record("POST /records", True, f"status={status}")

        status, body = http_get("/records")
        titles = [r.get("title") for r in json.loads(body).get("records", [])]
        found = "validate.py check" in titles
        record("GET /records reflects created record", found,
               "" if found else "not found in list")
    except Exception as e:
        record("records create/list", False, str(e))


def check_counter():
    try:
        _, body1 = http_get("/counter")
        count1 = json.loads(body1).get("counter")
        _, body2 = http_get("/counter")
        count2 = json.loads(body2).get("counter")
        increased = isinstance(count1, int) and isinstance(count2, int) and count2 > count1
        record("counter increments via Redis", increased, f"first={count1} second={count2}")
    except Exception as e:
        record("counter increments via Redis", False, str(e))


def check_both_backends(max_attempts=20):
    seen = set()
    try:
        for _ in range(max_attempts):
            _, body = http_get("/instance")
            seen.add(json.loads(body).get("instance_id"))
            if {"app-01", "app-02"} <= seen:
                break
        ok = {"app-01", "app-02"} <= seen
        record("both backends serve traffic", ok, f"instances seen={sorted(seen)}")
    except Exception as e:
        record("both backends serve traffic", False, str(e))


def run_compose(*args):
    result = subprocess.run(["docker", "compose", *args], capture_output=True, text=True, timeout=15)
    return result.returncode, result.stdout, result.stderr


def check_no_published_db_ports():
    try:
        rc, out, err = run_compose("ps", "--format", "json")
        if rc != 0:
            record("no published PostgreSQL/Redis ports", False, err.strip())
            return
        out = out.strip()
        try:
            parsed = json.loads(out)
            containers = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            containers = [json.loads(line) for line in out.splitlines() if line.strip()]
        offenders = [c.get("Service") for c in containers
                     if c.get("Service") in ("postgres", "redis") and c.get("Publishers")]
        record("no published PostgreSQL/Redis ports", not offenders,
               f"published for: {offenders}" if offenders else "")
    except Exception as e:
        record("no published PostgreSQL/Redis ports", False, str(e))


def check_network_isolation():
    """NGINX must not reach postgres/redis directly (different Docker network)."""
    for service, port in (("postgres", 5432), ("redis", 6379)):
        try:
            rc, out, err = run_compose("exec", "-T", "nginx", "nc", "-z", "-w", "2", service, str(port))
            record(f"nginx cannot reach {service}:{port}", rc != 0, (out + err).strip())
        except Exception as e:
            record(f"nginx cannot reach {service}:{port}", False, str(e))


def main():
    global BASE_URL
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()
    BASE_URL = args.base_url

    check_public_access()
    if wait_for_ready():
        for path in ("/", "/health", "/instance"):
            check_endpoint(path)
        check_records()
        check_counter()
        check_both_backends()
    check_no_published_db_ports()
    check_network_isolation()

    failed = [name for name, passed, _ in RESULTS if not passed]
    print("\n--- summary ---")
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("failed checks:", ", ".join(failed))
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()