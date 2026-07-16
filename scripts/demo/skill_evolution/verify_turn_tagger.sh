#!/usr/bin/env bash
# Verify the turn tagger against simulator-tagged conversations.
#
# Strips simulator tags, re-infers them from raw text, and compares.
#
# Usage:
#   bash scripts/demo/skill_evolution/verify_turn_tagger.sh
#   bash scripts/demo/skill_evolution/verify_turn_tagger.sh -i eval/runs/.../v0_traffic.json
#   bash scripts/demo/skill_evolution/verify_turn_tagger.sh -n 5   # limit to 5 conversations

set -euo pipefail
cd "$(dirname "$0")/../../.."

source .env 2>/dev/null || true

# Default to the most recent demo_quick run's traffic file
DEFAULT_INPUT=$(ls -dt eval/runs/*demo_quick/v*_traffic.json 2>/dev/null | head -1)
INPUT="${DEFAULT_INPUT}"
N_FLAG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -i|--input) INPUT="$2"; shift 2 ;;
        -n)         N_FLAG="-n $2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [-i INPUT] [-n LIMIT]"
            echo "  -i  Path to traffic JSON (default: latest demo_quick v*_traffic.json)"
            echo "  -n  Limit to N conversations"
            exit 0
            ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done

if [[ -z "$INPUT" || ! -f "$INPUT" ]]; then
    echo "No input file found. Run the demo first or pass -i <path>."
    exit 1
fi

echo "Input: $INPUT"
echo ""

uv run python eval/scoring/verify_turn_tagger.py -i "$INPUT" $N_FLAG
