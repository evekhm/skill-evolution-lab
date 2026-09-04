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
    echo "MODE: DEPLOYED — SDK Cloud Run job 'bqaa-skill-evolution' in project ${PROJECT_ID} (winner -> Skill Registry + real PR)"
    # Guarantee the baseline: the deployed supervisor serves whatever the
    # registry's newest revision is. A previous run's evolved push (kept
    # while its PR awaits review) would silently replace V0 in the "V0
    # baseline" traffic and poison both the baseline and the training
    # signal. Roll back to content-verified V0 before every run.
    echo "Ensuring registry + agents serve V0 (rollback with content verification)..."
    bash "$(dirname "${BASH_SOURCE[0]}")/rollback_demo.sh"
    # Per-execution demo overrides on top of the deploy-time lab wiring
    # (EVOLUTION_HOOKS, SDK_REPO/SDK_BRANCH, scoping + model IDs — see
    # agents/workflow/skill_evolution_agent/deploy.sh): synthetic quality
    # source drives the traffic hook, the 13-question lite set replaces
    # the 55-question evolve default, and a 1h report window isolates the
    # fresh V0 sessions the traffic hook just wrote. EVOLUTION_MAX_ROUNDS=1
    # and EVOLUTION_CANDIDATES=2 are binding in the job's tools (the
    # orchestrating agent cannot exceed them) — the lite profile is one
    # round of two candidates, same as the local sandbox.
    OVERRIDES="^|^QUALITY_SOURCE=synthetic|EVAL_QUESTIONS_FILE=eval/data/questions/two_defect_lite.json|EVAL_TIME_PERIOD=1h|MIN_SESSIONS=13|MIN_FAILURES=5|EVOLUTION_TARGET_AGENTS=supervisor|EVOLUTION_CANDIDATES=2|EVOLUTION_MAX_ROUNDS=1"
    JOB_ARGS=""
    for a in ${ARGS[@]+"${ARGS[@]}"}; do [ -n "$a" ] && JOB_ARGS="${JOB_ARGS:+$JOB_ARGS,}$a"; done
    # --project is REQUIRED: gcloud config is shared across VM sessions
    # and can be flipped mid-run — an ambient-config execute once launched
    # this job in a different project entirely.
    exec gcloud run jobs execute bqaa-skill-evolution \
        --project "$PROJECT_ID" --region "$REGION" --wait \
        --update-env-vars "$OVERRIDES" ${JOB_ARGS:+--args="$JOB_ARGS"}
fi
echo "MODE: LOCAL sandbox — in-process agents, nothing published"
exec bash scripts/demo/skill_evolution/run_demo.sh --quick ${ARGS[@]+"${ARGS[@]}"}
