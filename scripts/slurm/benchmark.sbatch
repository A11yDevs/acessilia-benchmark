#!/usr/bin/env bash
# Submit from the benchmark checkout with its shared storage mounted on the node.
# Resource requests (partition, GPU, CPUs, RAM, time) belong to the sbatch invocation.
#SBATCH --job-name=acessilia-benchmark
#SBATCH --output=benchmark-%j.log
set -euo pipefail

: "${ACESSILIA_BENCHMARK_WORKSPACE:?Set the absolute benchmark checkout path}"
: "${ACESSILIA_REPO:?Set the absolute Core checkout path}"
: "${RUN:?Set a unique run name, or the existing run to resume}"
DATASET=${DATASET:-drdocbench-dev}
PROFILE=${PROFILE:-auto}
ENGINE=${ENGINE:-pipeline}
WINDOW_SIZE=${WINDOW_SIZE:-1}
LIMIT=${LIMIT:-0}
SEED=${SEED:-42}
TIMEOUT=${TIMEOUT:-1800}
EVALUATION_TIMEOUT=${EVALUATION_TIMEOUT:-7200}

cd "$ACESSILIA_BENCHMARK_WORKSPACE"
# Never interpolate RUN into shell source. Validate before probing its directory.
[[ "$RUN" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$ ]] || { echo 'Invalid RUN' >&2; exit 1; }
bench=(uv run --no-sync acessilia-benchmark)
options=(--engine "$ENGINE")
[[ -z "${PROVIDER:-}" ]] || options+=(--provider "$PROVIDER")
[[ -z "${ACESSILIA_PYTHON:-}" ]] || options+=(--python "$ACESSILIA_PYTHON")

# Prepare datasets, evaluator runtime and renderers before scheduling jobs.
# Toolbox/providers must already be reachable from the compute node.
if [[ ! -f "runs/$RUN/plan.json" ]]; then
    "${bench[@]}" prepare "$DATASET" --run "$RUN" --window-size "$WINDOW_SIZE" \
        --limit "$LIMIT" --seed "$SEED" --data-dir "${BENCHMARK_DATA_DIR:-$PWD/data}"
fi
uv run --no-sync python - "$RUN" "$DATASET" "$WINDOW_SIZE" "$LIMIT" "$SEED" <<'PYTHON'
import json
import sys
plan = json.load(open("runs/" + sys.argv[1] + "/plan.json"))
expected = (sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]))
actual = (plan["dataset"], plan.get("window_size", 2), plan["limit"], plan["seed"])
if plan["dataset"] == "omnidocbench":
    expected = (expected[0], 1, *expected[2:])
if actual != expected:
    raise SystemExit("Existing plan differs from DATASET/WINDOW_SIZE/LIMIT/SEED")
PYTHON
resume=()
[[ ! -f "runs/$RUN/inference.json" ]] || resume=(--resume)
"${bench[@]}" predict --run "$RUN" --acessilia-repo "$ACESSILIA_REPO" \
    --timeout "$TIMEOUT" "${options[@]}" "${resume[@]}"
# evaluate preserves existing quality artifacts: rerunning a finished job skips them.
if [[ "$PROFILE" == auto ]]; then
    PROFILE=$(uv run --no-sync python -c \
        'import json,sys; print("full" if json.load(open(sys.argv[1]))["evaluator"] else "runtime")' \
        "runs/$RUN/plan.json")
fi
if [[ "$PROFILE" == runtime || ! -d "runs/$RUN/$PROFILE" ]]; then
    "${bench[@]}" evaluate --run "$RUN" --profile "$PROFILE" --timeout "$EVALUATION_TIMEOUT"
fi
# Also validate previously completed artifacts instead of silently accepting a stale directory.
"${bench[@]}" compare "$RUN" "$RUN" --profile "$PROFILE" >/dev/null
