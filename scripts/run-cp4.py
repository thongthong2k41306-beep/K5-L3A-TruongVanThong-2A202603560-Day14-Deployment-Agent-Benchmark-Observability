"""Run CP4 samples, SIGTERM probe and 3-instance Redis session checks in WSL.

From repo root: .venv/core/bin/python scripts/run-cp4.py
Only this run's temporary app and k5-day14-scaling stack are stopped/removed.
"""
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
PRODUCTION = ROOT / "05-scaling-reliability/production"
PROJECT = "k5-day14-scaling"
BASE = "http://127.0.0.1:8080"


def command(args, *, cwd=ROOT, timeout=120):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args)}\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def compose(*args, timeout=120):
    return command(["docker", "compose", "-p", PROJECT, *args], cwd=PRODUCTION, timeout=timeout)


def http(base, method, path, body=None):
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(base + path, data=payload, method=method,
                  headers={"Content-Type": "application/json"} if payload else {})
    try:
        response = urlopen(req, timeout=10)
    except HTTPError as exc:
        response = exc
    with response:
        return {"method": method, "path": path, "request_body": body,
                "status": response.code, "body": json.loads(response.read().decode("utf-8")),
                "headers": dict(response.headers)}


def wait_http(base, path="/health", timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            result = http(base, "GET", path)
            if result["status"] == 200:
                return result
        except (URLError, OSError, ValueError):
            pass
        time.sleep(.2)
    raise TimeoutError(f"Timed out: {base}{path}")


def develop_probe():
    folder = ROOT / "05-scaling-reliability/develop"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # Keep the app's real entry point, lifespan and signal handlers. Only extend
    # mock latency and add a marker so SIGTERM is sent while LLM work is active.
    bootstrap = """import pathlib, runpy, sys
from utils import mock_llm
original = mock_llm.ask
marker = pathlib.Path(sys.argv[1])
def observed_ask(question, delay=0.1):
    marker.write_text('request_in_flight', encoding='utf-8')
    return original(question, delay=1.0)
mock_llm.ask = observed_ask
runpy.run_path('app.py', run_name='__main__')
"""
    with tempfile.TemporaryDirectory(prefix="cp4-") as tmp:
        marker = Path(tmp) / "in-flight.txt"
        logfile = Path(tmp) / "app.log"
        env = dict(os.environ, PORT=str(port), ENVIRONMENT="development",
                   PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
        with logfile.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen([sys.executable, "-c", bootstrap, str(marker)], cwd=folder,
                                    env=env, stdout=log, stderr=log)
            worker = None
            try:
                base = f"http://127.0.0.1:{port}"
                health = wait_http(base)
                ready = http(base, "GET", "/ready")
                assert health["status"] == ready["status"] == 200
                holder = {}

                def ask():
                    started = time.monotonic()
                    try:
                        holder["response"] = http(base, "POST", "/ask?question=Hello")
                    except Exception as exc:
                        holder["error"] = str(exc)
                    holder["duration_seconds"] = round(time.monotonic() - started, 3)

                worker = threading.Thread(target=ask)
                worker.start()
                end = time.monotonic() + 10
                while not marker.exists():
                    if time.monotonic() > end or not worker.is_alive():
                        raise RuntimeError(f"No in-flight marker: {holder}")
                    time.sleep(.005)
                assert worker.is_alive(), "Request finished before SIGTERM probe"
                sent = time.monotonic()
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=15)
                worker.join(timeout=15)
                elapsed = round(time.monotonic() - sent, 3)
                assert holder.get("response", {}).get("status") == 200, holder
                assert proc.returncode == 0, proc.returncode
                text = logfile.read_text(encoding="utf-8")
                assert "Shutdown complete" in text
                (REPORTS / "cp4-graceful.log").write_text(text, encoding="utf-8")
                return {"base_url": base, "health": health, "ready": ready,
                        "probe": "Original app.py via runpy; mock delay 1.0s only in test process; source unchanged",
                        "sigterm_sent_after_in_flight_marker": True, "request": holder,
                        "exit_code": proc.returncode, "shutdown_seconds_after_sigterm": elapsed,
                        "log": "reports/cp4-graceful.log"}
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                if worker is not None:
                    worker.join(timeout=15)


def container_health(container):
    code = "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health'))))"
    return json.loads(command(["docker", "exec", container, "python", "-c", code]))


def stack_probe():
    if compose("ps", "-a", "-q"):
        raise RuntimeError(f"Project {PROJECT} already exists; refusing to replace another stack")
    startup_log = REPORTS / "cp4-compose-start.log"
    phase = "startup"
    try:
        args = ["docker", "compose", "-p", PROJECT, "up", "-d", "--build", "--scale", "agent=3",
                "--wait", "--wait-timeout", "180"]
        with startup_log.open("w", encoding="utf-8") as log:
            result = subprocess.run(args, cwd=PRODUCTION, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
        if result.returncode:
            raise RuntimeError(f"Compose startup failed; see {startup_log.relative_to(ROOT)}")
        wait_http(BASE, "/ready")
        ids = compose("ps", "-q", "agent").splitlines()
        assert len(ids) == 3, ids
        initial_checks = [http(BASE, "GET", "/health"), http(BASE, "GET", "/ready")]
        assert all(r["status"] == 200 for r in initial_checks)
        ps = [json.loads(line) for line in compose("ps", "--format", "json").splitlines() if line.strip()]
        services = [{key: row.get(key, "") for key in ("Name", "Service", "Image", "State", "Health", "Ports")}
                    for row in ps]
        print("Three agent containers healthy; running original test_stateless.py", flush=True)
        phase = "original_stateless_script"
        output = command([sys.executable, "test_stateless.py"], cwd=PRODUCTION)
        (REPORTS / "cp4-stateless.txt").write_text(output + "\n", encoding="utf-8")
        session_id = re.search(r"Session ID: ([a-f0-9-]+)", output).group(1)
        instances = re.findall(r"Request \d+: \[([^\]]+)\]", output)
        assert len(instances) == 5 and len(set(instances)) > 1, instances
        history_path = f"/chat/{session_id}/history"
        history = http(BASE, "GET", history_path)
        assert history["status"] == 200 and history["body"]["count"] == 10
        roles = [m["role"] for m in history["body"]["messages"]]
        assert roles == ["user", "assistant"] * 5
        more = []
        phase = "extend_session"
        for number in range(1, 4):
            item = http(BASE, "POST", "/chat", {"question": f"CP4 shared session {number}", "session_id": session_id})
            assert item["status"] == 200 and item["body"]["storage"] == "redis"
            more.append(item)
        extended_history = http(BASE, "GET", history_path)
        assert extended_history["body"]["count"] == 16
        victim = ids[0]
        before = container_health(victim)
        phase = "restart_agent"
        command(["docker", "restart", victim], timeout=90)
        end = time.monotonic() + 60
        while True:
            try:
                after = container_health(victim)
                if after["redis_connected"] is True:
                    break
            except (RuntimeError, ValueError):
                pass
            if time.monotonic() > end:
                raise TimeoutError("Agent did not recover after restart")
            time.sleep(.5)
        assert before["instance_id"] != after["instance_id"]
        after_restart = http(BASE, "GET", history_path)
        assert after_restart["status"] == 200 and after_restart["body"]["count"] == 16
        continued = http(BASE, "POST", "/chat", {"question": "Continue after agent restart", "session_id": session_id})
        assert continued["status"] == 200 and continued["body"]["storage"] == "redis"
        final_history = http(BASE, "GET", history_path)
        assert final_history["body"]["count"] == 18
        # Separate real dependency failure: keep app processes alive, stop only
        # this test stack's Redis, then bring the same Redis container back.
        phase = "redis_down_health"
        print("Session preserved after agent restart; checking Redis failure probes", flush=True)
        compose("pause", "redis")
        try:
            down_health = http(BASE, "GET", "/health")
            phase = "redis_down_ready"
            down_ready = http(BASE, "GET", "/ready")
            assert down_health["status"] == 200 and down_health["body"]["redis_connected"] is False
            assert down_ready["status"] == 503
        finally:
            compose("unpause", "redis")
        phase = "redis_recovery"
        recovered_ready = wait_http(BASE, "/ready")
        rawlogs = compose("logs", "--no-color")
        (REPORTS / "cp4-compose.log").write_text(rawlogs + "\n", encoding="utf-8")
        return {"project": PROJECT, "base_url": BASE, "agent_count": len(ids), "services": services,
                "health_checks": initial_checks, "original_script_output": "reports/cp4-stateless.txt",
                "session_id": session_id, "served_by_first_five": instances,
                "original_history": history, "additional_requests": more, "extended_history": extended_history,
                "agent_restart": {"before": before, "after": after, "history_after": after_restart,
                                  "continued_request": continued, "final_history": final_history},
                "redis_down": {"health": down_health, "ready": down_ready},
                "redis_recovered_ready": recovered_ready, "log": "reports/cp4-compose.log"}
    except Exception as exc:
        try:
            (REPORTS / "cp4-compose.log").write_text(compose("logs", "--no-color") + "\n", encoding="utf-8")
        except Exception:
            pass
        raise RuntimeError(f"{phase}: {exc}") from exc
    finally:
        compose("down", timeout=180)


def main():
    REPORTS.mkdir(exist_ok=True)
    report = {"checkpoint": "CP4", "part": 5,
              "run_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(),
              "python": sys.version.split()[0], "os_name": os.name}
    target = REPORTS / "cp4-runtime.json"
    try:
        print("Checking health/readiness and SIGTERM during an in-flight request", flush=True)
        report["develop"] = develop_probe()
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Graceful shutdown passed; building three-instance Compose stack", flush=True)
        report["production"] = stack_probe()
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error"] = str(exc)
        print(str(exc), file=sys.stderr, flush=True)
    finally:
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "evidence": str(target.relative_to(ROOT))}, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
