#!/usr/bin/env bash
# Send traffic to Knowledge Supervisor agents (local or deployed).
#
# Modes:
#   Single query (no args or -q):
#     ./scripts/demo/generate_traffic.sh                            # default question
#     ./scripts/demo/generate_traffic.sh -q "What is our PTO policy?"
#     ./scripts/demo/generate_traffic.sh -q "PTO policy?" --remote  # deployed agents
#
#   Batch multi-turn (--from-file):
#     ./scripts/demo/generate_traffic.sh --from-file eval/data/questions/demo_quick.json
#     ./scripts/demo/generate_traffic.sh --from-file eval/data/questions/full_205.json --remote
#     ./scripts/demo/generate_traffic.sh --from-file questions.json --output results.json
#     ./scripts/demo/generate_traffic.sh --from-file questions.json --concurrency 5
#
# By default runs against local agents. Pass --remote to hit deployed agents.
# All unrecognized flags are passed through to the Python traffic generator.

set -euo pipefail
cd "$(dirname "$0")/../.."

source .env 2>/dev/null || true
unset SUPERVISOR_VERTEX_PROMPT_ID

# ── Parse flags ──────────────────────────────────────────────────────────────
REMOTE=false
BATCH=false
SINGLE_Q=""
PASSTHROUGH=()

i=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --remote)
            REMOTE=true; shift ;;
        --from-file|--questions)
            BATCH=true; PASSTHROUGH+=("$1" "$2"); shift 2 ;;
        -q|--question)
            SINGLE_Q="$2"; shift 2 ;;
        *)
            PASSTHROUGH+=("$1"); shift ;;
    esac
done

# ── Mode: local vs remote ───────────────────────────────────────────────────
MODE_ARGS=()
if ! $REMOTE; then
    MODE_ARGS=(--local --local-agents)
fi

# ── Single-query mode (no --from-file) ───────────────────────────────────────
if ! $BATCH; then
    SINGLE_Q="${SINGLE_Q:-What is our PTO policy?}"
    MODE_LABEL="local"
    $REMOTE && MODE_LABEL="remote (deployed)"

    echo "=== Single Query ($MODE_LABEL) ==="
    echo "  Q: $SINGLE_Q"
    echo ""

    uv run python3 agents/workflow/traffic_generator/main.py \
        -q "$SINGLE_Q" \
        --concurrency 1 \
        "${MODE_ARGS[@]}" \
        "${PASSTHROUGH[@]}"
    exit 0
fi

# ── Batch multi-turn mode (--from-file) ──────────────────────────────────────
CONCURRENCY="${CONCURRENCY:-10}"
MAX_TURNS="${MAX_TURNS:-4}"

# Inject --output default if not provided
HAS_OUTPUT=false
for arg in "${PASSTHROUGH[@]}"; do
    case "$arg" in --output|-o) HAS_OUTPUT=true ;; esac
done
OUTPUT="${OUTPUT:-eval/runs/$(date +%Y-%m-%d_%H%M%S)/traffic.json}"
if ! $HAS_OUTPUT; then
    PASSTHROUGH+=(--output "$OUTPUT")
    mkdir -p "$(dirname "$OUTPUT")"
fi

MODE_LABEL="local"
$REMOTE && MODE_LABEL="remote (deployed)"

echo "=== Batch Traffic ($MODE_LABEL) ==="
echo "  Concurrency: $CONCURRENCY"
echo "  Max turns:   $MAX_TURNS"
echo ""

uv run python3 agents/workflow/traffic_generator/main.py \
    --multi-turn \
    --max-turns "$MAX_TURNS" \
    --concurrency "$CONCURRENCY" \
    "${MODE_ARGS[@]}" \
    "${PASSTHROUGH[@]}"
