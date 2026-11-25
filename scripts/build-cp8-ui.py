"""Build the offline CP8 dashboard data from the saved runtime evidence."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def report(name):
    return json.loads((ROOT / "reports" / name).read_text(encoding="utf-8"))


def scale(replicas):
    with (ROOT / "benchmark-results" / f"scale_{replicas}_stats.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        row = next(row for row in csv.DictReader(stream) if row["Name"] == "Aggregated")
    return {
        "replicas": replicas,
        "count": int(row["Request Count"]),
        "failures": int(row["Failure Count"]),
        "rps": float(row["Requests/s"]),
        "p50": float(row["50%"]),
        "p95": float(row["95%"]),
        "p99": float(row["99%"]),
    }


def main():
    stages = report("cp8-alert-timeline.json")["stages"]
    alerts = []
    for stage, name, variable in zip(
        stages,
        ("AgentHighErrorRate", "AgentHighLatencyP95"),
        ("MOCK_ERROR_RATE", "MOCK_SLOW_RATE"),
        strict=True,
    ):
        observed = stage["first_firing"][name]
        alerts.append({
            "name": name, "variable": variable, "injected": stage["faults"][variable],
            "seconds": observed["observed_after_seconds"],
            "observed": float(observed["alerts"][0]["value"]),
        })
    dashboard = {
        "history": report("cp8-grafana-history.json"),
        "scales": [scale(1), scale(3)],
        "alerts": alerts,
        "traces": report("cp8-trace-summary.json"),
    }
    script = "// Generated from CP8 reports and Locust CSV by scripts/build-cp8-ui.py.\n"
    script += "window.CP8_DATA = " + json.dumps(dashboard, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (ROOT / "cp8-ui" / "data.js").write_text(script, encoding="utf-8")


if __name__ == "__main__":
    main()
