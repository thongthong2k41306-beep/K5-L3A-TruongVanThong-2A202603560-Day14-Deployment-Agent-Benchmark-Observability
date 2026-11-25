#!/usr/bin/env bash
# Run from Ubuntu WSL: bash scripts/setup-wsl.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ $(uname -s) != Linux ]]; then
  echo 'Run this script in Ubuntu WSL2.' >&2
  exit 1
fi
python3 -m venv .venv/core
.venv/core/bin/python -m pip install --disable-pip-version-check -q \
  -r 06-lab-complete/requirements.txt \
  -r 06-lab-complete/benchmark-observability/develop/requirements.txt
python3 -m venv .venv/gateway
.venv/gateway/bin/python -m pip install --disable-pip-version-check -q \
  -r 04-api-gateway/production/requirements.txt httpx==0.27.2
python3 -m venv .venv/observability
.venv/observability/bin/python -m pip install --disable-pip-version-check -q \
  -r 06-lab-complete/benchmark-observability/production/requirements.txt httpx==0.27.2
for profile in core gateway observability; do
  ".venv/$profile/bin/python" -m pip check
done
.venv/core/bin/python - <<'PY'
from pathlib import Path
import secrets

def create(path, content):
    target = Path(path)
    if not target.exists():
        target.write_text(content, encoding="utf-8")
        target.chmod(0o600)
        print(f"Created local config: {path}")

create("01-localhost-vs-production/production/.env",
       Path("01-localhost-vs-production/production/.env.example").read_text(encoding="utf-8"))
for path in ("02-docker/production/.env.local", "05-scaling-reliability/production/.env.local"):
    create(path, "# Local lab configuration; mock LLM needs no provider API key.\n")
create("06-lab-complete/.env", "PORT=8000\nENVIRONMENT=development\n"
       f"AGENT_API_KEY={secrets.token_urlsafe(32)}\n"
       "REDIS_URL=redis://localhost:6379/0\nRATE_LIMIT_PER_MINUTE=10\nDAILY_BUDGET_USD=1.0\n")
create("06-lab-complete/benchmark-observability/production/.env",
       Path("06-lab-complete/benchmark-observability/production/.env.example").read_text(encoding="utf-8"))
PY
echo 'Ready. Activate the main environment: source .venv/core/bin/activate'
echo 'Part 4 production: source .venv/gateway/bin/activate'
echo 'Part 7 production Python: source .venv/observability/bin/activate'
