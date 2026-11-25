"""Additional CP5 checks: real Compose, input errors and concurrent guards.

Run in Ubuntu: .venv/core/bin/python scripts/probe-cp5.py
Random API keys stay in memory/environment and are never saved to reports.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
LAB = ROOT / "06-lab-complete"
REPORTS = ROOT / "reports"
PROJECT = "k5-day14-final-probe"


def main():
    REPORTS.mkdir(exist_ok=True)
    secret = secrets.token_urlsafe(32)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    namespace = "cp5-probe-" + uuid.uuid4().hex[:10]
    env = dict(os.environ, PORT=str(port), AGENT_API_KEY=secret)
    report = {"run_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(),
              "base_url": base, "project": PROJECT}

    with tempfile.TemporaryDirectory(prefix="cp5-compose-") as temp:
        override = Path(temp) / "probe.json"

        def configure(environment, limit, budget):
            override.write_text(json.dumps({"services": {"agent": {"environment": {
                "ENVIRONMENT": environment, "RATE_LIMIT_PER_MINUTE": str(limit),
                "DAILY_BUDGET_USD": str(budget), "REDIS_TIMEOUT_SECONDS": "1"}}}}), encoding="utf-8")

        def run(args, timeout=180):
            result = subprocess.run(args, cwd=LAB, env=env, capture_output=True,
                                    text=True, encoding="utf-8", timeout=timeout)
            if result.returncode:
                raise RuntimeError((result.stdout + result.stderr).replace(secret, "[REDACTED]"))
            return result.stdout.strip()

        def compose(*args, timeout=180):
            return run(["docker", "compose", "-p", PROJECT, "-f", "docker-compose.yml",
                        "-f", str(override), *args], timeout=timeout)

        def http(path, body=None, *, key=secret, raw=None):
            data = raw if raw is not None else json.dumps(body).encode("utf-8") if body is not None else None
            headers = {"Content-Type": "application/json"} if data is not None else {}
            if key is not None:
                headers["X-API-Key"] = key
            req = Request(base + path, data=data, method="POST" if data is not None else "GET", headers=headers)
            try:
                response = urlopen(req, timeout=10)
            except HTTPError as exc:
                response = exc
            with response:
                return {"status": response.code, "body": json.loads(response.read().decode("utf-8")),
                        "headers": dict(response.headers)}

        def wait_ready():
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    response = http("/ready")
                    if response["status"] == 200:
                        return response
                except (OSError, URLError):
                    pass
                time.sleep(.3)
            raise TimeoutError("Compose agent did not become ready")

        def ledger(environment):
            keys = compose("exec", "-T", "redis", "redis-cli", "--raw", "--scan", "--pattern",
                           f"production-agent:{environment}:budget:*").splitlines()
            assert len(keys) == 1, keys
            return int(compose("exec", "-T", "redis", "redis-cli", "--raw", "GET", keys[0]))

        configure(namespace, 5, 1000)
        if compose("ps", "-a", "-q"):
            raise RuntimeError("Probe project already exists; refusing to replace it")
        try:
            print("Starting actual CP5 Compose agent + Redis", flush=True)
            startup = compose("up", "-d", "--build", "--wait", "--wait-timeout", "180", timeout=1200)
            (REPORTS / "cp5-compose-start.log").write_text(startup, encoding="utf-8")
            report["ready"] = wait_ready()
            checks = []
            for label, expected, kwargs in [
                ("missing_key", 401, {"body": {"question": "Hello"}, "key": None}),
                ("wrong_key", 401, {"body": {"question": "Hello"}, "key": "wrong-demo-key"}),
                ("missing_question", 422, {"body": {}}),
                ("empty_question", 422, {"body": {"question": ""}}),
                ("blank_question", 422, {"body": {"question": "   "}}),
                ("long_question", 422, {"body": {"question": "a" * 2001}}),
                ("malformed_json", 422, {"raw": b"{"}),
            ]:
                result = http("/ask", **kwargs)
                assert result["status"] == expected, (label, result)
                checks.append({"label": label, **result})
            report["input_auth_checks"] = checks
            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=20) as pool:
                responses = list(pool.map(lambda _: http("/ask", {"question": "What is Docker?"}), range(40)))
            elapsed = time.monotonic() - started
            codes = [response["status"] for response in responses]
            assert codes.count(200) == 5 and codes.count(429) == 35 and elapsed < 60, codes
            expected_units = int(sum(Decimal(str(x["body"]["usage"]["cost_usd"]))
                                     for x in responses if x["status"] == 200) * 1_000_000_000)
            assert ledger(namespace) == expected_units
            report["concurrent_rate"] = {"requests": 40, "concurrency": 20,
                "duration_seconds": round(elapsed, 3), "successful": 5, "rate_limited": 35,
                "ledger_nanodollars": expected_units, "responses": responses}
            compose("restart", "agent")
            wait_ready()
            report["after_restart"] = http("/ask", {"question": "Hello"})
            assert report["after_restart"]["status"] == 429
            compose("pause", "redis")
            try:
                down = {"health": http("/health"), "ready": http("/ready"),
                        "ask": http("/ask", {"question": "Hello"})}
                assert [down[k]["status"] for k in ("health", "ready", "ask")] == [200, 503, 503]
                assert down["ask"]["body"] == {"detail": "Storage temporarily unavailable"}
                report["redis_down"] = down
            finally:
                compose("unpause", "redis")
            report["redis_recovered"] = wait_ready()
            # Docker's health status updates on its next scheduled probe, after
            # HTTP readiness can already be back. Wait before Compose checks
            # service_healthy while recreating the agent for the budget test.
            redis_id = compose("ps", "-q", "redis")
            deadline = time.monotonic() + 30
            while run(["docker", "inspect", "--format", "{{.State.Health.Status}}", redis_id]) != "healthy":
                if time.monotonic() > deadline:
                    raise TimeoutError("Redis container health did not recover")
                time.sleep(.5)

            budget_namespace = namespace + "-budget"
            budget = Decimal("0.00005")
            configure(budget_namespace, 1000, budget)
            compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "180")
            wait_ready()
            with ThreadPoolExecutor(max_workers=20) as pool:
                responses = list(pool.map(lambda _: http("/ask", {"question": "What is Docker?"}), range(40)))
            codes = [response["status"] for response in responses]
            assert set(codes) == {200, 402}, codes
            total = sum(Decimal(str(x["body"]["usage"]["cost_usd"]))
                        for x in responses if x["status"] == 200)
            units = ledger(budget_namespace)
            assert units == int(total * 1_000_000_000) and total <= budget
            report["concurrent_budget"] = {"requests": 40, "concurrency": 20,
                "budget_usd": str(budget), "successful": codes.count(200),
                "budget_rejected": codes.count(402), "actual_cost_usd": str(total),
                "ledger_nanodollars": units, "responses": responses}
            agent_id = compose("ps", "-q", "agent")
            image_id = run(["docker", "inspect", "--format", "{{.Image}}", agent_id])
            details = json.loads(run(["docker", "image", "inspect", image_id]))[0]
            report["image"] = {"id": image_id, "size_bytes": details["Size"],
                "size_mb": round(details["Size"] / 1_000_000, 2), "size_mib": round(details["Size"] / 1024**2, 2),
                "user": details["Config"].get("User", "")}
            report["pid1"] = compose("exec", "-T", "agent", "python", "-c",
                                    "from pathlib import Path; print(Path('/proc/1/comm').read_text().strip())")
            assert report["pid1"] == "uvicorn"
            logs = compose("logs", "--no-color", "--no-log-prefix", "agent")
            json_logs = [json.loads(line) for line in logs.splitlines() if line.startswith("{")]
            assert json_logs and secret not in logs
            report["valid_json_app_log_lines"] = len(json_logs)
            (REPORTS / "cp5-compose-app.log").write_text(logs + "\n", encoding="utf-8")
            report["passed"] = True
        except Exception as exc:
            report["passed"] = False
            report["error"] = str(exc).replace(secret, "[REDACTED]")
            print(report["error"], file=sys.stderr, flush=True)
        finally:
            compose("down", "--volumes")
            output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            assert secret not in output
            (REPORTS / "cp5-probes.json").write_text(output, encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "evidence": "reports/cp5-probes.json"}, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
