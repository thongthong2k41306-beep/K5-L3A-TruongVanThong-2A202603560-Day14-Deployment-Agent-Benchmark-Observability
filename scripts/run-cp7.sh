#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root/06-lab-complete/benchmark-observability/develop"
python="$root/.venv/observability/bin/python"
logs="$root/.venv/cp7-logs"
mkdir -p reports "$logs"
declare -A agents=()

stop_agent() {
    local port=$1
    if [[ -n "${agents[$port]:-}" ]]; then
        kill "${agents[$port]}" 2>/dev/null || true
        wait "${agents[$port]}" 2>/dev/null || true
        unset "agents[$port]"
    fi
}
trap 'stop_agent 8001; stop_agent 8002' EXIT

start_agent() {
    local version=$1 port=$2 slow=$3 errors=$4
    stop_agent "$port"
    AGENT_VERSION="$version" PORT="$port" MOCK_SLOW_RATE="$slow" MOCK_ERROR_RATE="$errors" \
        "$python" app.py >"$logs/server-${version}.log" 2>&1 &
    agents[$port]=$!
    for ((attempt=0; attempt<240; attempt++)); do
        if ! kill -0 "${agents[$port]}" 2>/dev/null; then
            break
        fi
        if curl -fs --max-time 1 "http://127.0.0.1:$port/metrics" -o /dev/null; then
            return
        fi
        sleep 0.25
    done
    tail -n 30 "$logs/server-${version}.log" >&2
    return 1
}

load_test() {
    local concurrency=$1 output=$2 status=0
    rm -f -- "$output"
    "$python" load_test.py --url http://127.0.0.1:8002 --requests 300 \
        --concurrency "$concurrency" --out "$output" || status=$?
    [[ $status -le 1 && -s "$output" ]]
}

case "${1:-}" in
    baseline)
        # Run before adding the two knowledge base entries.
        start_agent v1 8001 0 0
        start_agent v2 8002 0 0
        curl -fsS -X POST http://127.0.0.1:8002/ask -H 'Content-Type: application/json' \
            -d '{"question":"Prometheus thu thập metrics như thế nào?"}' >reports/ask_sample.json
        curl -fsS http://127.0.0.1:8002/metrics >reports/metrics_sample.txt
        status=0
        "$python" eval/run_eval.py --url http://127.0.0.1:8001 --out reports/eval_v1.json || status=$?
        [[ $status -eq 1 ]]
        "$python" eval/run_eval.py --url http://127.0.0.1:8002 \
            --baseline reports/eval_v1.json --out reports/eval_v2.json
        status=0
        "$python" eval/run_eval.py --url http://127.0.0.1:8001 \
            --baseline reports/eval_v2.json --out reports/eval_v1_regression.json || status=$?
        [[ $status -eq 1 ]]
        ;;
    load)
        start_agent v2 8002 0.03 0.01
        for concurrency in 1 10 50 100; do
            load_test "$concurrency" "reports/load_v2_c${concurrency}.json"
        done
        for slow in 0 0.03 0.1; do
            start_agent v2 8002 "$slow" 0.01
            load_test 20 "reports/load_v2_slow_${slow}.json"
        done
        ;;
    fixed)
        start_agent v2 8002 0 0
        curl -fsS -X POST http://127.0.0.1:8002/ask -H 'Content-Type: application/json' \
            -d '{"question":"Hello"}' >/dev/null
        curl -fsS http://127.0.0.1:8002/metrics >reports/metrics_question_length.txt
        grep -Fx 'agent_question_length_chars_count 1.0' reports/metrics_question_length.txt
        grep -Fx 'agent_question_length_chars_sum 5.0' reports/metrics_question_length.txt
        "$python" eval/run_eval.py --url http://127.0.0.1:8002 --min-accuracy 1.0 \
            --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json
        ;;
    *)
        echo "Usage: bash scripts/run-cp7.sh {baseline|load|fixed}" >&2
        exit 2
        ;;
esac
