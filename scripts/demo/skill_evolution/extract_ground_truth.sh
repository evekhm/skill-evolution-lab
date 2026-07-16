#!/usr/bin/env bash
# Extract ground truth from golden Q&A eval pairs using an LLM.
#
# Usage:
#   ./scripts/demo/skill_evolution/extract_ground_truth.sh -i eval/data/golden_evals.json
#   ./scripts/demo/skill_evolution/extract_ground_truth.sh -i eval/data/golden_evals.json \
#       --update-config eval/data/agent_context.json

set -euo pipefail
cd "$(dirname "$0")/../../.."

source .env 2>/dev/null || true

echo "=== Extract Ground Truth from Golden Evals ==="
uv run python3 eval/scoring/extract_ground_truth.py "$@"
