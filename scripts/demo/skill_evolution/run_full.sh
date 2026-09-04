#!/usr/bin/env bash
# Full profile — ~1-2 h. 55 questions + held-out split (local);
# agent-decided rounds/candidates/targets.
#   run_full.sh              SDK Cloud Run job with its default env —
#                            identical to the weekly scheduled run
#   run_full.sh --local      local sandbox (nothing published)
# Extra args pass through (local: to run_demo.sh; deployed: to the job).
set -euo pipefail
cd "$(dirname "$0")/../../.."
TARGET=deployed; ARGS=()
for a in "$@"; do case "$a" in
    --deployed) TARGET=deployed ;;
    --local)    TARGET=local ;;
    *)          ARGS+=("$a") ;;
esac; done
if [ "$TARGET" = deployed ]; then
    set -a; source .env; set +a
    echo "MODE: DEPLOYED — SDK Cloud Run job 'bqaa-skill-evolution' in project ${PROJECT_ID} (winner -> Skill Registry + real PR)"
    # Guarantee the baseline: the registry's newest revision is what fresh
    # supervisor instances serve. Roll back to content-verified V0 before
    # every run so the V0 traffic measures V0, not a leftover evolved push.
    echo "Ensuring registry + agents serve V0 (rollback with content verification)..."
    bash "$(dirname "${BASH_SOURCE[0]}")/rollback_demo.sh"
    # --project is REQUIRED: gcloud config is shared across VM sessions
    # and can be flipped mid-run (see run_lite.sh).
    exec gcloud run jobs execute bqaa-skill-evolution \
        --project "$PROJECT_ID" --region "$REGION" --wait
fi
echo "MODE: LOCAL sandbox — in-process agents, nothing published"
exec bash scripts/demo/skill_evolution/run_demo.sh --full ${ARGS[@]+"${ARGS[@]}"}
