#!/usr/bin/env bash
# Component 2: Score conversations (turn tagging + quality judge + trace retrieval).
#
# Usage:
#   ./scripts/demo/skill_evolution/score.sh -i eval/runs/.../traffic.json
#   ./scripts/demo/skill_evolution/score.sh -i results.json -o report.json --report
#   ./scripts/demo/skill_evolution/score.sh -i results.json --eval-spec none  # disable
#
# Scope grounding and golden-Q&A matching are configured by the eval spec,
# auto-discovered from eval/data/eval_spec.json (pass --eval-spec to override).

set -euo pipefail
cd "$(dirname "$0")/../../.."

source .env 2>/dev/null || true
CONCURRENCY="${CONCURRENCY:-10}"

echo "=== SDK Scorer (turn tags + traces) ==="
uv run python3 eval/scoring/score_conversations.py \
    --tag-turns \
    --trajectory-samples all \
    --concurrency "$CONCURRENCY" \
    "$@"
