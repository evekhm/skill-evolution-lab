#!/usr/bin/env bash
# Full profile — ~1-2 h. 55 questions + held-out split (local);
# agent-decided rounds/candidates/targets.
#   run_full.sh              local sandbox (nothing published)
#   run_full.sh --deployed   Cloud Run job with its default args —
#                            identical to the weekly scheduled run
# Extra args pass through (local: to run_demo.sh; deployed: to the job).
set -euo pipefail
cd "$(dirname "$0")/../../.."
TARGET=local; ARGS=()
for a in "$@"; do case "$a" in
    --deployed) TARGET=deployed ;;
    --local)    TARGET=local ;;
    *)          ARGS+=("$a") ;;
esac; done
if [ "$TARGET" = deployed ]; then
    set -a; source .env; set +a
    exec gcloud run jobs execute skill-evolution-agent \
        --region "$REGION" --wait
fi
exec bash scripts/demo/skill_evolution/run_demo.sh --full ${ARGS[@]+"${ARGS[@]}"}
