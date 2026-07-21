#!/usr/bin/env bash
# Standard profile — ~30-40 min local. 25 questions, 3 candidates,
# 1 round, supervisor target.
#   run_standard.sh              local sandbox (nothing published)
#   run_standard.sh --deployed   Cloud Run job: winner -> registry + real PR
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
    JOB_ARGS="--full-loop,--mode,supervisor,--rounds,1,--candidates,3,--quick"
    for a in ${ARGS[@]+"${ARGS[@]}"}; do [ -n "$a" ] && JOB_ARGS="$JOB_ARGS,$a"; done
    exec gcloud run jobs execute skill-evolution-agent \
        --region "$REGION" --wait --args="$JOB_ARGS"
fi
exec bash scripts/demo/skill_evolution/run_demo.sh --quick \
    --questions eval/data/questions/two_defect_quick.json \
    --candidates 3 ${ARGS[@]+"${ARGS[@]}"}
