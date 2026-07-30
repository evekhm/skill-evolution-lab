#!/usr/bin/env bash
# Lite profile — ~17 min local. 13 questions, 2 candidates, 1 round,
# supervisor target.
#   run_lite.sh              Cloud Run job: winner -> registry + real PR
#   run_lite.sh --local      local sandbox (nothing published)
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
    echo "MODE: DEPLOYED — Cloud Run job 'skill-evolution-agent' in project ${PROJECT_ID} (winner -> Skill Registry + real PR)"
    # Guarantee the baseline: the deployed supervisor serves whatever the
    # registry's newest revision is. A previous run's evolved push (kept
    # while its PR awaits review) would silently replace V0 in the "V0
    # baseline" traffic and poison both the baseline and the training
    # signal. Roll back to content-verified V0 before every run.
    echo "Ensuring registry + agents serve V0 (rollback with content verification)..."
    bash "$(dirname "${BASH_SOURCE[0]}")/rollback_demo.sh"
    # --questions keeps the deployed run on the SAME 13-question lite set as
    # the local run (it forces EVAL_QUESTIONS_FILE past the container's
    # env default, which points at the full 55-question evolve set).
    JOB_ARGS="--full-loop,--mode,supervisor,--rounds,1,--candidates,2,--quick,--questions,/app/eval/data/questions/two_defect_lite.json,--quality-source,synthetic"
    for a in ${ARGS[@]+"${ARGS[@]}"}; do [ -n "$a" ] && JOB_ARGS="$JOB_ARGS,$a"; done
    exec gcloud run jobs execute skill-evolution-agent \
        --region "$REGION" --wait --args="$JOB_ARGS"
fi
echo "MODE: LOCAL sandbox — in-process agents, nothing published"
exec bash scripts/demo/skill_evolution/run_demo.sh --quick ${ARGS[@]+"${ARGS[@]}"}
