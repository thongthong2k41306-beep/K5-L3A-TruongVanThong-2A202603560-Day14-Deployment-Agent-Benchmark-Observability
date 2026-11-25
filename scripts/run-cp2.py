"""Build, run and measure CP2 using Docker Desktop from Ubuntu WSL2.

Run from the repository root: .venv/core/bin/python scripts/run-cp2.py
The script removes only its temporary containers and its own Compose stack.
Compose volumes are kept. Raw build logs and HTTP evidence go to reports/.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
PROJECT = "k5-day14-docker"
COMPOSE_DIR = ROOT / "02-docker/production"


def command(args, *, cwd=ROOT, timeout=120):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args)}\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def compose(*args, timeout=120):
    return command(["docker", "compose", "-p", PROJECT, "-f", "docker-compose.yml",
                    "-f", "compose.cp2-local.yml", *args], cwd=COMPOSE_DIR, timeout=timeout)


def service_status():
    rows = [json.loads(line) for line in compose("ps", "--format", "json").splitlines() if line.strip()]
    return [{key: row.get(key, "") for key in ("Name", "Service", "Image", "State", "Health", "Ports")}
            for row in rows]


def http(base, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(base + path, data=data, method=method,
                  headers={"Content-Type": "application/json"} if data else {})
    try:
        response = urlopen(req, timeout=10)
    except HTTPError as exc:
        response = exc
    with response:
        return {"method": method, "path": path, "request_body": body,
                "status": response.code, "body": json.loads(response.read().decode("utf-8")),
                "headers": dict(response.headers)}


def wait_health(base, *, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if http(base, "GET", "/health")["status"] == 200:
                return
        except (URLError, OSError, ValueError):
            pass
        time.sleep(1)
    raise TimeoutError(f"No healthy response from {base}")


def save(report):
    (REPORTS / "cp2-runtime.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build(variant, tag):
    args = ["docker", "build", "--progress=plain", "-f", f"02-docker/{variant}/Dockerfile", "-t", tag, "."]
    target = REPORTS / f"cp2-build-{variant}.log"
    print(f"Building {tag}; log: {target.relative_to(ROOT)}", flush=True)
    started = time.monotonic()
    with target.open("w", encoding="utf-8") as log:
        result = subprocess.run(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    if result.returncode:
        raise RuntimeError(f"Build failed: see {target}")
    details = json.loads(command(["docker", "image", "inspect", tag]))[0]
    return {"tag": tag, "command": args, "build_seconds": round(time.monotonic() - started, 2),
            "image_id": details["Id"], "size_bytes": details["Size"],
            "size_mb": round(details["Size"] / 1_000_000, 2),
            "size_mib": round(details["Size"] / 1024**2, 2), "user": details["Config"].get("User", ""),
            "cmd": details["Config"]["Cmd"], "build_log": str(target.relative_to(ROOT))}


def run_image(tag, variant):
    name = f"k5-cp2-{variant}-{uuid.uuid4().hex[:8]}"
    command(["docker", "run", "-d", "--name", name, "-p", "127.0.0.1::8000", tag])
    try:
        binding = json.loads(command(["docker", "inspect", name]))[0]["NetworkSettings"]["Ports"]["8000/tcp"][0]
        base = f"http://127.0.0.1:{binding['HostPort']}"
        wait_health(base)
        checks = [http(base, "GET", "/health")]
        checks.append(http(base, "POST", "/ask?question=What%20is%20Docker?") if variant == "develop"
                      else http(base, "POST", "/ask", {"question": "What is Docker?"}))
        if variant == "production":
            checks.append(http(base, "GET", "/ready"))
        assert all(c["status"] == 200 for c in checks), checks
        return {"base_url": base, "requests": checks}
    finally:
        command(["docker", "rm", "-f", name])


def main():
    REPORTS.mkdir(exist_ok=True)
    report = {"checkpoint": "CP2", "run_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(),
              "docker_version": command(["docker", "version", "--format", "{{.Server.Version}}"]),
              "compose_version": command(["docker", "compose", "version"]), "images": []}
    try:
        for variant, tag in [("develop", "my-agent:develop"), ("production", "my-agent:advanced")]:
            item = build(variant, tag)
            report["images"].append(item)
            save(report)
            item["runtime"] = run_image(tag, variant)
            print(f"{tag}: {item['size_mb']} MB; HTTP checks passed", flush=True)
            save(report)
        dev, prod = report["images"]
        report["size_reduction_percent"] = round((dev["size_bytes"] - prod["size_bytes"]) / dev["size_bytes"] * 100, 2)
        report["docker_images_output"] = command(["docker", "images", "my-agent"])
        print(report["docker_images_output"], flush=True)
        # Refuse to take down a stack that existed before this run.
        existing = compose("ps", "-a", "-q")
        if existing:
            raise RuntimeError(f"Project {PROJECT} already exists; inspect it before rerunning")
        print("Starting Compose: agent + Redis + Qdrant + Nginx", flush=True)
        try:
            output = compose("up", "-d", "--build", "--wait", "--wait-timeout", "180", timeout=1200)
            base = "http://127.0.0.1:8085"
            wait_health(base)
            checks = [http(base, "GET", "/health"),
                      http(base, "POST", "/ask", {"question": "Explain microservices"}),
                      http(base, "GET", "/ready")]
            assert all(c["status"] == 200 for c in checks), checks
            report["compose"] = {"project": PROJECT, "base_url": base,
                "override": "compose.cp2-local.yml", "startup_output": output,
                "ps": service_status(), "requests_via_nginx": checks,
                "redis_ping": compose("exec", "-T", "redis", "redis-cli", "ping"),
                "qdrant_health": compose("exec", "-T", "agent", "python", "-c",
                    "import urllib.request; r=urllib.request.urlopen('http://qdrant:6333/healthz'); print(r.status); print(r.read().decode())"),
                "agent_user": compose("exec", "-T", "agent", "id"),
                "nginx_config_check": compose("exec", "-T", "nginx", "nginx", "-t") or "passed (exit code 0)"}
            (REPORTS / "cp2-compose.log").write_text(compose("logs", "--no-color"), encoding="utf-8")
        finally:
            compose("down", timeout=180)
        report["passed"] = True
        print(f"CP2 passed; image size reduction: {report['size_reduction_percent']}%", flush=True)
    except Exception as exc:
        report["passed"] = False
        report["error"] = str(exc)
        print(str(exc), file=sys.stderr, flush=True)
    finally:
        save(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
