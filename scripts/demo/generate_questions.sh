#!/usr/bin/env bash
# Generate synthetic questions for eval and demo use.
#
# Usage:
#   ./scripts/demo/generate_questions.sh                          # 10 questions
#   ./scripts/demo/generate_questions.sh --count 20               # 20 questions
#   ./scripts/demo/generate_questions.sh --output my_questions.json # custom output

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load .env
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
COUNT=10
OUTPUT="$PROJECT_ROOT/reports/demo_traffic.json"

# Parse arguments (extract for banner, pass through to Python)
ARGS=("$@")
i=0
while [[ $i -lt ${#ARGS[@]} ]]; do
    case "${ARGS[$i]}" in
        --count)
            COUNT="${ARGS[$((i+1))]}"
            i=$((i+2))
            ;;
        --output)
            OUTPUT="${ARGS[$((i+1))]}"
            i=$((i+2))
            ;;
        *)
            i=$((i+1))
            ;;
    esac
done

MODEL="${EVAL_MODEL_ID:-gemini-2.5-flash}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
separator() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

step_start() { STEP_START_TIME=$(date +%s); }
step_end() {
    local elapsed=$(( $(date +%s) - STEP_START_TIME ))
    echo ""
    echo "  Done. ${1:-Step} completed in ${elapsed}s."
}

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
separator
echo ""
echo "  GENERATE SYNTHETIC TRAFFIC"
echo ""
echo "  Project:  ${GOOGLE_CLOUD_PROJECT}"
echo "  Region:   ${GOOGLE_CLOUD_LOCATION}"
echo "  Model:    ${MODEL}"
echo "  Count:    ${COUNT} questions"
echo "  Output:   ${OUTPUT}"

# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------
separator
echo ""
echo "  Goal:    Produce diverse user questions that differ from the golden eval set"
echo "  Method:  Gemini generates ${COUNT} questions across all policy categories"
echo ""
step_start

cd "$PROJECT_ROOT"
uv run python3 agents/workflow/traffic_generator/main.py \
    --generate-only \
    --eval-format \
    --count "$COUNT" \
    --output "$OUTPUT"

# Count actual cases (may be fewer than requested after dedup)
ACTUAL_COUNT=$(jq '.eval_cases | length' "$OUTPUT" 2>/dev/null || echo "?")

echo ""
echo "  Generated questions saved to: $OUTPUT"
echo "  Requested: $COUNT, Generated: $ACTUAL_COUNT (after dedup)"
echo ""
echo "  Sample questions:"
jq -r '.eval_cases[:5][] | "    - [\(.category // "?")] \(.question)"' "$OUTPUT" 2>/dev/null || true

step_end "Traffic generation"
separator
echo ""
