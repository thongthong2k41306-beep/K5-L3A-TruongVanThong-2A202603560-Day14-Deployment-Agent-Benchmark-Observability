"""Collect CP3 API security evidence using real curl -i requests in Ubuntu.

Run from repo root: .venv/gateway/bin/python scripts/run-cp3.py
JWTs and keys are held in memory and redacted before saving reports.
The cost-guard probe changes only an isolated process's test budget, not source.
"""
import json
import os
from pathlib import Path
import secrets
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from urllib.error import URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import jwt


ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
SIGNING_KEY = secrets.token_urlsafe(48)
API_KEY = secrets.token_urlsafe(32)
REDACTIONS = [SIGNING_KEY, API_KEY]


def redact(text):
    for value in sorted(REDACTIONS, key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    return text


@contextmanager
def server(variant, *, budget_probe=False):
    profile = "core" if variant == "develop" else "gateway"
    python = str(ROOT / ".venv" / profile / "bin/python")
    folder = ROOT / "04-api-gateway" / variant
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, JWT_SECRET=SIGNING_KEY, AGENT_API_KEY=API_KEY,
               ENVIRONMENT="development", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    args = [python, "-m", "uvicorn", "app:app", "--host", "127.0.0.1",
            "--port", str(port), "--workers", "1", "--no-access-log"]
    if budget_probe:
        code = ("import uvicorn; from app import app; from cost_guard import cost_guard; "
                "cost_guard.daily_budget_usd = 0.000001; "
                f"uvicorn.run(app, host='127.0.0.1', port={port}, access_log=False)")
        args = [python, "-c", code]
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
        proc = subprocess.Popen(args, cwd=folder, env=env, stdout=log, stderr=log)
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 30
            while True:
                if proc.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(redact(log.read()))
                try:
                    with urlopen(base + "/health", timeout=2) as response:
                        if response.status == 200:
                            break
                except (URLError, OSError):
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"{variant} startup timed out")
                    time.sleep(.1)
            yield base
        finally:
            proc.terminate()
            try:
                proc.wait(15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def curl(base, method, path, *, body=None, headers=None):
    args = ["curl", "--silent", "--show-error", "--include", "--max-time", "15",
            "--request", method, base + path]
    for name, value in (headers or {}).items():
        args.extend(["--header", f"{name}: {value}"])
    if body is not None:
        args.extend(["--header", "Content-Type: application/json", "--data", json.dumps(body)])
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=20)
    if result.returncode:
        raise RuntimeError(redact(result.stderr))
    raw_headers, raw_body = result.stdout.split("\n\n", 1)
    response_body = json.loads(raw_body)
    if isinstance(response_body, dict) and response_body.get("access_token"):
        token = response_body["access_token"]
        REDACTIONS.extend([token, token[:20]])
    response_headers = {}
    for line in raw_headers.splitlines()[1:]:
        name, _, value = line.partition(":")
        response_headers[name.lower()] = value.strip()
    record = {"method": method, "path": path, "status": int(raw_headers.split()[1]),
              "headers": response_headers, "body": json.loads(redact(raw_body)),
              "command": redact(shlex.join(args)), "curl_output": redact(result.stdout)}
    return record, response_body


def check(records, label, expected, *args, **kwargs):
    record, body = curl(*args, **kwargs)
    record.update(label=label, expected_status=expected, passed=record["status"] == expected)
    records.append(record)
    assert record["passed"], f"{label}: HTTP {record['status']} (expected {expected})"
    return body


def main():
    REPORTS.mkdir(exist_ok=True)
    checks = []
    report = {"checkpoint": "CP3", "part": 4,
              "run_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(),
              "python": sys.version.split()[0], "os_name": os.name, "checks": checks}
    try:
        with server("develop") as base:
            report["develop_url"] = base
            payload = {"question": "What is Docker?"}
            check(checks, "api_key_missing", 401, base, "POST", "/ask", body=payload)
            check(checks, "api_key_wrong", 403, base, "POST", "/ask", body=payload,
                  headers={"X-API-Key": "wrong-demo-key"})
            check(checks, "api_key_valid", 200, base, "POST", "/ask", body=payload,
                  headers={"X-API-Key": API_KEY})
        with server("production") as base:
            report["production_url"] = base
            check(checks, "login_wrong_password", 401, base, "POST", "/auth/token",
                  body={"username": "student", "password": "wrong-demo-password"})
            login = check(checks, "login_student", 200, base, "POST", "/auth/token",
                          body={"username": "student", "password": "demo123"})
            token = login["access_token"]
            claims = jwt.decode(token, SIGNING_KEY, algorithms=["HS256"])
            report["verified_jwt_claims"] = claims
            assert claims["exp"] - claims["iat"] == 3600
            auth = {"Authorization": f"Bearer {token}"}
            check(checks, "jwt_missing", 401, base, "POST", "/ask", body=payload)
            check(checks, "jwt_invalid", 403, base, "POST", "/ask", body=payload,
                  headers={"Authorization": "Bearer invalid-demo-token"})
            expired = jwt.encode({"sub": "student", "role": "user", "exp": int(time.time()) - 60},
                                 SIGNING_KEY, algorithm="HS256")
            REDACTIONS.extend([expired, expired[:20]])
            check(checks, "jwt_expired", 401, base, "POST", "/ask", body=payload,
                  headers={"Authorization": f"Bearer {expired}"})
            check(checks, "student_admin_denied", 403, base, "GET", "/admin/stats", headers=auth)
            check(checks, "empty_question", 422, base, "POST", "/ask", body={"question": ""}, headers=auth)
            started = time.monotonic()
            for number in range(1, 21):
                check(checks, f"burst_{number:02}", 200 if number <= 10 else 429,
                      base, "POST", "/ask", body={"question": f"Rate limit test {number}"}, headers=auth)
            elapsed = time.monotonic() - started
            burst = [r for r in checks if r["label"].startswith("burst_")]
            assert elapsed < 60
            assert all("retry-after" in r["headers"] for r in burst if r["status"] == 429)
            report["burst"] = {"requests": 20, "duration_seconds": round(elapsed, 3),
                               "successful": 10, "rate_limited": 10, "limit_per_60_seconds": 10}
            usage = check(checks, "usage_after_burst", 200, base, "GET", "/me/usage", headers=auth)
            assert usage["requests"] == 10
        with server("production", budget_probe=True) as base:
            report["budget_probe"] = {"url": base, "daily_budget_usd": 0.000001,
                "method": "Override CostGuard.daily_budget_usd only inside a separate test process; source unchanged"}
            login = check(checks, "budget_login", 200, base, "POST", "/auth/token",
                          body={"username": "student", "password": "demo123"})
            auth = {"Authorization": f"Bearer {login['access_token']}"}
            check(checks, "budget_first_request", 200, base, "POST", "/ask", body=payload, headers=auth)
            check(checks, "budget_exhausted", 402, base, "POST", "/ask", body=payload, headers=auth)
        report["passed"] = all(r["passed"] for r in checks)
        report["checks_total"] = len(checks)
    except Exception as exc:
        report["passed"] = False
        report["error"] = redact(str(exc))
        print(report["error"], file=sys.stderr, flush=True)
    finally:
        serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        assert all(value not in serialized for value in REDACTIONS), "Secret found in report"
        (REPORTS / "cp3-runtime.json").write_text(serialized, encoding="utf-8")
        lines = [f"CP3 curl -i evidence | {report['run_at']}", "Tokens and keys are redacted."]
        for record in checks:
            lines.extend(["", f"=== {record['label']} ===", "$ " + record["command"], record["curl_output"]])
        (REPORTS / "cp3-curl.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": len(checks),
                      "burst": report.get("burst"), "evidence": "reports/cp3-runtime.json"}, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
