"""Verify CP6 over HTTPS; prompt for the key without printing or saving it."""
import argparse
import getpass
import json
import os
import subprocess
from pathlib import Path
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_URL = "https://k5-l3a-truongvanthong-2a202603560-day14.onrender.com"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--public-only", action="store_true", help="Run three checks without a key; CP6 remains incomplete")
    parser.add_argument("--clipboard", action="store_true", help="On Windows, read the key from the clipboard after an Enter prompt")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("Use a public HTTPS URL without credentials, query, or fragment")
    key = ""
    if not args.public_only:
        if args.clipboard:
            if os.name != "nt":
                parser.error("--clipboard requires Windows Python; run this command in PowerShell")
            input("Copy the Render AGENT_API_KEY, return here, then press Enter (do not paste): ")
            powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            try:
                result = subprocess.run(
                    [str(powershell), "-NoProfile", "-NonInteractive", "-Command",
                     "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-Clipboard -Raw"],
                    capture_output=True, encoding="utf-8-sig", check=True, timeout=15,
                )
            except (OSError, subprocess.SubprocessError):
                parser.error("Could not read Windows clipboard; no key was printed or saved")
            key = result.stdout.strip()
            if any(character.isspace() for character in key):
                parser.error("Clipboard contains whitespace; copy only the API key value from Render")
        else:
            key = os.environ.get("AGENT_API_KEY", "").strip() or getpass.getpass("Render AGENT_API_KEY (hidden): ").strip()
        if not key:
            parser.error("An API key is required for the fourth check")
    checks = [
        ("health", "GET", "/health", 200, False),
        ("ready", "GET", "/ready", 200, False),
        ("ask_without_key", "POST", "/ask", 401, False),
    ]
    if key:
        checks.append(("ask_with_key", "POST", "/ask", 200, True))
    results = []
    for label, method, path, expected, authenticated in checks:
        headers = {"Accept": "application/json"}
        data = None
        if method == "POST":
            headers["Content-Type"] = "application/json"
            data = json.dumps({"question": "Hello"}).encode()
        if authenticated:
            headers["X-API-Key"] = key
        request = Request(base + path, data=data, headers=headers, method=method)
        status = None
        error = None
        try:
            with urlopen(request, timeout=60) as response:
                status = response.status
                body = response.read(65536).decode("utf-8", errors="replace")
        except HTTPError as exc:
            status = exc.code
            body = exc.read(65536).decode("utf-8", errors="replace")
        except (URLError, TimeoutError, OSError) as exc:
            body = ""
            error = type(exc).__name__
        if key:
            body = body.replace(key, "[REDACTED]")
        try:
            payload = json.loads(body)
        except ValueError:
            payload = body[:500]
        passed = status == expected
        if passed and label == "health":
            passed = isinstance(payload, dict) and payload.get("status") == "ok"
        elif passed and label == "ready":
            passed = isinstance(payload, dict) and payload.get("ready") is True
        elif passed and label == "ask_with_key":
            passed = isinstance(payload, dict) and isinstance(payload.get("answer"), str) and bool(payload["answer"])
        results.append(dict(check=label, method=method, path=path, expected_status=expected,
                            status=status, passed=passed, body=payload, error=error))
        print(f"{label}: HTTP {status}, expected {expected}: {'PASS' if passed else 'FAIL'}", flush=True)
    report = dict(run_at=datetime.now(timezone.utc).isoformat(), base_url=base,
                  public_only=args.public_only, checks=results,
                  completed_checks=len(results), required_checks=4,
                  passed=len(results) == 4 and all(row["passed"] for row in results))
    destination = ROOT / "reports" / ("cp6-public-checks.json" if args.public_only else "cp6-runtime.json")
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved: {destination.relative_to(ROOT)}", flush=True)
    print("CP6 API checks: " + ("4/4 PASS" if report["passed"] else "incomplete or failed"))
    return 0 if report["passed"] or (args.public_only and all(row["passed"] for row in results)) else 1


if __name__ == "__main__":
    sys.exit(main())
