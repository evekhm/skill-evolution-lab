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
# Targets the DEPLOYED agents by default (consistent with the demo
# wrappers). Pass --local to run in-process local agents instead
# (--local --local-agents; zero requests to the deployed stack).
# All unrecognized flags are passed through to the Python traffic generator.

set -euo pipefail
cd "$(dirname "$0")/../.."

source .env 2>/dev/null || true
unset SUPERVISOR_VERTEX_PROMPT_ID

# ── Parse flags ──────────────────────────────────────────────────────────────
REMOTE=true
BATCH=false
SINGLE_Q=""
FROM_FILE=""
LIMIT=""
LABELS=""
PASSTHROUGH=()

i=1
while [[ $# -gt 0 ]]; do
    case "$1" in
        --remote)
            REMOTE=true; shift ;;
        --local)
            REMOTE=false; shift ;;
        --from-file|--questions)
            BATCH=true; FROM_FILE="$2"; PASSTHROUGH+=("$1" "$2"); shift 2 ;;
        --concurrency)
            CONCURRENCY="$2"; shift 2 ;;
        --limit)
            LIMIT="$2"; PASSTHROUGH+=("$1" "$2"); shift 2 ;;
        --label)
            LABELS="${LABELS:+$LABELS,}$2"; PASSTHROUGH+=("$1" "$2"); shift 2 ;;
        --output|-o)
            OUTPUT="$2"; PASSTHROUGH+=("$1" "$2"); shift 2 ;;
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
if [ -z "${OUTPUT:-}" ]; then
    OUTPUT="eval/runs/$(date +%Y-%m-%d_%H%M%S)/traffic.json"
    PASSTHROUGH+=(--output "$OUTPUT")
    mkdir -p "$(dirname "$OUTPUT")"
fi

MODE_LABEL="local"
$REMOTE && MODE_LABEL="remote (deployed)"

echo "=== Batch Traffic ($MODE_LABEL) ==="
echo "  Questions:   ${FROM_FILE}${LIMIT:+ (limit: $LIMIT)}"
echo "  Concurrency: $CONCURRENCY"
echo "  Max turns:   $MAX_TURNS"
[ -n "$LABELS" ] && echo "  Labels:      $LABELS"
echo "  Output:      $OUTPUT"
echo ""

uv run python3 agents/workflow/traffic_generator/main.py \
    --multi-turn \
    --max-turns "$MAX_TURNS" \
    --concurrency "$CONCURRENCY" \
    "${MODE_ARGS[@]}" \
    "${PASSTHROUGH[@]}"
