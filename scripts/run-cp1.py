"""Run the CP1 sample APIs on temporary ports and save actual HTTP evidence.

From the repository root in Ubuntu WSL:
    .venv/core/bin/python scripts/run-cp1.py
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent


def http(base, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(base + path, data=data, method=method,
                  headers={"Content-Type": "application/json"} if data else {})
    try:
        response = urlopen(req, timeout=10)
    except HTTPError as exc:
        response = exc
    with response:
        return {"method": method, "path": path, "status": response.code,
                "body": json.loads(response.read().decode("utf-8"))}


def run_variant(variant):
    folder = ROOT / "01-localhost-vs-production" / variant
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, HOST="127.0.0.1", PORT=str(port), DEBUG="false",
               ENVIRONMENT="development", PYTHONDONTWRITEBYTECODE="1",
               PYTHONUNBUFFERED="1", OPENAI_API_KEY="", AGENT_API_KEY="")
    # Keep the student's server on port 8000 running. The develop entry point
    # hardcodes that port, so launch its ASGI app with a temporary port instead.
    command = ([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
                "--port", str(port), "--no-access-log"] if variant == "develop"
               else [sys.executable, "app.py"])
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
        proc = subprocess.Popen(command, cwd=folder, env=env, stdout=log, stderr=log)
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 30
            while True:
                if proc.poll() is not None:
                    raise RuntimeError(f"{variant} exited before startup")
                try:
                    http(base, "GET", "/")
                    break
                except (URLError, OSError):
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"{variant} startup timed out")
                    time.sleep(.1)
            tests = ([("POST", "/ask?question=Hello", None, 200),
                      ("POST", "/ask", {"question": "Hello"}, 422),
                      ("GET", "/health", None, 404), ("GET", "/ready", None, 404)]
                     if variant == "develop" else
                     [("POST", "/ask", {"question": "Hello"}, 200),
                      ("GET", "/health", None, 200), ("GET", "/ready", None, 200),
                      ("POST", "/ask", {}, 422)])
            observations = []
            for method, path, body, expected in tests:
                result = http(base, method, path, body)
                result["request_body"] = body
                result["expected_status"] = expected
                result["passed"] = result["status"] == expected
                observations.append(result)
            return {"variant": variant, "base_url": base, "command": command,
                    "requests": observations}
        finally:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def main():
    report = {"checkpoint": "CP1", "run_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(),
              "python": sys.version.split()[0], "os_name": os.name,
              "variants": [run_variant("develop"), run_variant("production")]}
    report["passed"] = all(r["passed"] for v in report["variants"] for r in v["requests"])
    target = ROOT / "reports/cp1-runtime.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
