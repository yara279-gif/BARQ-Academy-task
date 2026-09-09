"""Recorded lab exercise. Never use this against non-assessment infrastructure."""
import argparse
import json
import secrets
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("app-01", "app-02", "nginx", "postgres", "redis")

def docker(*args):
    result = subprocess.run(["docker", *args], cwd=ROOT, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Docker operation failed")
    return result.stdout.strip()

def preflight(project, url):
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("Use this local assessment's loopback HTTP URL only")
    release = json.loads((ROOT / "RELEASE.json").read_text())
    if release.get("release") != "barq-devops-starter-v2.0.0":
        raise ValueError("This directory is not the v2 assessment")
    containers = {}
    for service in SERVICES:
        info = json.loads(docker("inspect", service))[0]
        labels = info.get("Config", {}).get("Labels", {})
        if labels.get("com.docker.compose.project") != project or labels.get("com.docker.compose.service") != service:
            raise ValueError("Container ownership does not match this assessment project")
        state = info["State"]
        if not state.get("Running") or state.get("Paused") or state.get("Health", {}).get("Status") != "healthy":
            raise ValueError("Repair the environment first: every service must be healthy and unpaused")
        containers[service] = info
    networks = {}
    for suffix in ("frontend", "backend"):
        candidates = containers["app-01"]["NetworkSettings"]["Networks"]
        matches = [name for name in candidates if name.endswith(suffix)]
        if len(matches) != 1:
            raise ValueError("Use unambiguous network names ending in frontend/backend")
        info = json.loads(docker("network", "inspect", matches[0]))[0]
        if info.get("Labels", {}).get("com.docker.compose.project") != project:
            raise ValueError("Network ownership does not match this assessment project")
        networks[suffix] = info["Id"]
    required = {"app-01": {"frontend", "backend"}, "app-02": {"frontend", "backend"},
                "nginx": {"frontend"}, "postgres": {"backend"}, "redis": {"backend"}}
    for service, expected in required.items():
        actual = {entry["NetworkID"] for entry in containers[service]["NetworkSettings"]["Networks"].values()}
        if actual != {networks[name] for name in expected}:
            raise ValueError("Complete the required network isolation before recording")
    seen = set()
    for _ in range(16):
        with urlopen(url.rstrip("/") + "/ready", timeout=5) as response:
            result = json.load(response)
        if result.get("status") != "ready":
            raise ValueError("Public dependency readiness did not pass")
        seen.add(result.get("instance_id"))
    if seen != {"app-01", "app-02"}:
        raise ValueError("Prove both initial instances before the recorded challenge")
    return containers, networks

def apply_challenge(project, url, choose=secrets.choice):
    state_dir = ROOT / ".assessment"
    state_dir.mkdir(exist_ok=True)
    lock = state_dir / "challenge.lock"
    if lock.exists():
        raise ValueError("Challenge already attempted in this working copy. Do not reset or rerun it")
    containers, networks = preflight(project, url)
    # Public, auditable safety code; first-run compliance is assessed using video evidence.
    actions = [("network", "disconnect", networks["frontend"], containers["app-02"]["Id"]),
               ("network", "disconnect", networks["backend"], containers["redis"]["Id"]),
               ("pause", containers["app-01"]["Id"])]
    lock.mkdir()  # Atomic: concurrent invocations cannot both inject a fault.
    receipt = {"id": uuid.uuid4().hex, "project": project,
               "started_utc": datetime.now(timezone.utc).isoformat(), "status": "started"}
    receipt_path = state_dir / "challenge.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    try:
        docker(*choose(actions))
        receipt["status"] = "applied"
    except Exception:
        receipt["status"] = "failed"
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print("Challenge applied. Diagnose the runtime fault and repair it without a full-stack reset.")
    print("Receipt:", receipt["id"])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    try:
        project = args.project or json.loads(docker("compose", "config", "--format", "json"))["name"]
        apply_challenge(project, args.url)
    except Exception as exc:
        print("Challenge stopped:", exc, file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
