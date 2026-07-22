#!/usr/bin/env bash
# Standard profile — ~90 min local. 25 questions, 3 candidates,
# 2 rounds (evolve, then evolve the survivors of round 1 again) —
# measured: 1 round stops at ~76% held-out, 2 rounds reach ~84%.
#   run_standard.sh              Cloud Run job: winner -> registry + real PR
#   run_standard.sh --local      local sandbox (nothing published)
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
    JOB_ARGS="--full-loop,--mode,supervisor,--rounds,2,--candidates,3,--quick"
    for a in ${ARGS[@]+"${ARGS[@]}"}; do [ -n "$a" ] && JOB_ARGS="$JOB_ARGS,$a"; done
    exec gcloud run jobs execute skill-evolution-agent \
        --region "$REGION" --wait --args="$JOB_ARGS"
fi
echo "MODE: LOCAL sandbox — in-process agents, nothing published"
exec bash scripts/demo/skill_evolution/run_demo.sh --quick \
    --questions eval/data/questions/two_defect_quick.json \
    --candidates 3 --rounds 2 ${ARGS[@]+"${ARGS[@]}"}
