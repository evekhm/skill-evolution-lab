#!/usr/bin/env bash
# Component 2: Score conversations (turn tagging + quality judge + trace retrieval).
#
# Usage:
#   ./scripts/demo/skill_evolution/score.sh -i eval/runs/.../traffic.json
#   ./scripts/demo/skill_evolution/score.sh -i results.json -o report.json --report
#   ./scripts/demo/skill_evolution/score.sh -i results.json --golden-evals none  # disable

set -euo pipefail
cd "$(dirname "$0")/../../.."

source .env 2>/dev/null || true
CONCURRENCY="${CONCURRENCY:-10}"

GOLDEN_EVALS_ARGS=()
GOLDEN_EVALS_DEFAULT="eval/data/golden_evals.json"
if [[ -f "$GOLDEN_EVALS_DEFAULT" ]] && ! echo "$*" | grep -q -- "--golden-evals"; then
    GOLDEN_EVALS_ARGS=(--golden-evals "$GOLDEN_EVALS_DEFAULT")
fi

echo "=== SDK Scorer (turn tags + traces) ==="
uv run python3 eval/scoring/score_conversations.py \
    --tag-turns \
    --trajectory-samples all \
    --concurrency "$CONCURRENCY" \
    "${GOLDEN_EVALS_ARGS[@]}" \
    "$@"
