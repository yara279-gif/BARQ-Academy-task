import sys
import json
import time
import subprocess
import urllib.request

BASE_URL = "http://127.0.0.1:8080"
TARGET_SERVICE = "app-01"
RESULTS = []


def record(name, passed, detail=""):
    RESULTS.append((name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


def http_get(path, timeout=3):
    req = urllib.request.Request(BASE_URL + path, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8")


def run_compose(*args):
    result = subprocess.run(["docker", "compose", *args], capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout, result.stderr


def burst_requests(n=20, path="/instance", delay=0.2):
    """Send n requests, return (successes, errors, instance_ids_seen)."""
    successes, errors, instances = 0, 0, set()
    for _ in range(n):
        try:
            status, body = http_get(path)
            if status == 200:
                successes += 1
                instances.add(json.loads(body).get("instance_id"))
            else:
                errors += 1
        except Exception:
            errors += 1
        time.sleep(delay)
    return successes, errors, instances


def wait_until_healthy(service, max_attempts=20, delay=1.5):
    for attempt in range(1, max_attempts + 1):
        rc, out, _ = run_compose("ps", service, "--format", "json")
        out = out.strip()
        if rc == 0 and out:
            try:
                data = json.loads(out.splitlines()[0])
            except json.JSONDecodeError:
                data = json.loads(out)
            if data.get("Health") == "healthy":
                return True, attempt
        time.sleep(delay)
    return False, max_attempts


def main():
    successes, errors, instances = burst_requests(n=10)
    record("baseline: both backends reachable", {"app-01", "app-02"} <= instances,
           f"instances seen={sorted(instances)}")

    rc, _, err = run_compose("stop", TARGET_SERVICE)
    record(f"stop {TARGET_SERVICE}", rc == 0, err.strip() if rc != 0 else "")

    successes, errors, instances = burst_requests(n=20)
    total = successes + errors
    error_rate = (errors / total * 100) if total else 100
    record("service stays available while one backend is down",
           successes > 0 and TARGET_SERVICE not in instances,
           f"{successes}/{total} succeeded ({error_rate:.1f}% errors), instances seen={sorted(instances)}")

    rc, _, err = run_compose("start", TARGET_SERVICE)
    record(f"restart {TARGET_SERVICE}", rc == 0, err.strip() if rc != 0 else "")

    healthy, attempt = wait_until_healthy(TARGET_SERVICE)
    record(f"{TARGET_SERVICE} becomes healthy again", healthy,
           f"after {attempt} attempt(s)" if healthy else "gave up waiting")

    successes, errors, instances = burst_requests(n=20)
    record("recovered backend serves requests again", TARGET_SERVICE in instances,
           f"instances seen={sorted(instances)}")

    failed = [name for name, passed, _ in RESULTS if not passed]
    print("\n--- summary ---")
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("failed checks:", ", ".join(failed))
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()