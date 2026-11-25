"""Run the unmodified CP5 checker in WSL and retain its actual output."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
LAB = ROOT / "06-lab-complete"
REPORTS = ROOT / "reports"
PROTECTED = ["06-lab-complete/check_production_ready.py",
             "06-lab-complete/benchmark-observability/develop/eval/golden_dataset.jsonl"]


def protected_files():
    records = []
    for name in PROTECTED:
        original = subprocess.check_output(["git", "show", f"HEAD:{name}"], cwd=ROOT)
        current = (ROOT / name).read_bytes()
        # Git's checkout may convert LF to CRLF without changing the source.
        normalized_original = original.replace(b"\r\n", b"\n")
        normalized_current = current.replace(b"\r\n", b"\n")
        assert normalized_current == normalized_original, f"Protected file changed: {name}"
        records.append({"path": name, "sha256": hashlib.sha256(current).hexdigest(),
                        "matches_git_source": True})
    return records


def main():
    if os.name != "posix":
        raise SystemExit("Run this script inside Ubuntu WSL2")
    REPORTS.mkdir(exist_ok=True)
    report = {"checkpoint": "CP5", "part": 6,
              "run_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(),
              "python": sys.version.split()[0], "os_name": os.name,
              "protected_files": protected_files()}
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    # Let the original checker create and clean up its own temporary Redis.
    env.pop("REDIS_URL", None)
    for label, flags in [("static", ["--static-only"]), ("production-ready", [])]:
        logpath = REPORTS / f"cp5-{label}.txt"
        print(f"Running original checker ({label}); log: {logpath.relative_to(ROOT)}", flush=True)
        with logpath.open("w", encoding="utf-8") as log:
            proc = subprocess.run([sys.executable, "check_production_ready.py", *flags],
                                  cwd=LAB, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1500)
        output = logpath.read_text(encoding="utf-8")
        result = re.search(r"Result: (\d+)/12.*?(\d+)/(\d+) checks passed", output)
        report[label] = {"command": ["python", "check_production_ready.py", *flags],
                         "exit_code": proc.returncode, "log": str(logpath.relative_to(ROOT)),
                         "criteria_passed": int(result[1]) if result else None,
                         "checks_passed": int(result[2]) if result else None,
                         "checks_total": int(result[3]) if result else None}
        if label == "production-ready":
            report["passed"] = proc.returncode == 0 and "PASS 12/12" in output
            print("\n".join(output.splitlines()[-20:]), flush=True)
    report["protected_files"] = protected_files()
    (REPORTS / "cp5-runtime.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
