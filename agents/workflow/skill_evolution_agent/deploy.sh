#!/bin/bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Deploy skill evolution as the SDK's generic Cloud Run Job.
#
# The evolution runner no longer ships as a lab-built image. The
# BigQuery-Agent-Analytics-SDK provides a generic scheduled job
# (deploy/skill_evolution_job/) — quality report from BigQuery ->
# bottleneck analysis -> candidate evolution -> publish gate -> GitHub
# PR — and this lab plugs into it through the EVOLUTION_HOOKS seam:
# eval/skill_evolution_hooks.py (traffic, score, gate, toolbox,
# error_analyst, publish), which the job imports from a fresh clone of
# this repo at runtime. The lab's Python harness modules under this
# directory (main.py, tools.py, evolve.py, agentic_analyst.py, ...)
# remain as the hook implementations; only the deployment surface
# (Dockerfile, image build, the skill-evolution-weekly scheduler)
# is replaced by the SDK job `bqaa-skill-evolution` and its
# `bqaa-skill-evolution-cron` trigger.
#
# This script:
#   1. Obtains an SDK checkout that carries deploy/skill_evolution_job
#      (SDK_JOB_DIR if set, else a shallow clone of SDK_JOB_REPO at
#      SDK_JOB_BRANCH).
#   2. Runs the SDK's deploy.sh with this lab's parameters (+ --smoke).
#   3. Persists the lab wiring on the job: EVOLUTION_HOOKS, the
#      SDK_REPO/SDK_BRANCH pair ensure_sdk.py needs in-cloud, quality
#      scoping and model IDs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
ENV_PATH="${PROJECT_ROOT}/.env"

if [ -f "${ENV_PATH}" ]; then
    # shellcheck disable=SC1090
    set -a; source "${ENV_PATH}"; set +a
else
    echo "Warning: .env file not found at ${ENV_PATH}"
fi

: "${PROJECT_ID:?PROJECT_ID must be set (see .env)}"
: "${REGION:?REGION must be set (see .env)}"

JOB_NAME="bqaa-skill-evolution"

# PR target repo: explicit env wins, else derived from origin.
if [ -z "${GITHUB_REPO:-}" ]; then
    GITHUB_REPO=$(git -C "${PROJECT_ROOT}" remote get-url origin 2>/dev/null \
        | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##') || true
fi

# SDK checkout that contains deploy/skill_evolution_job. Until the
# upstream PR lands on main, the default branch is the port branch on
# the fork (same repo ensure_sdk.py clones for the engine).
SDK_JOB_REPO="${SDK_JOB_REPO:-${SDK_REPO:-https://github.com/evekhm/BigQuery-Agent-Analytics-SDK.git}}"
SDK_JOB_BRANCH="${SDK_JOB_BRANCH:-feat/skill-evolution-job}"

if [ -z "${SDK_JOB_DIR:-}" ]; then
    SDK_JOB_DIR="$(mktemp -d)/BigQuery-Agent-Analytics-SDK"
    echo "Cloning ${SDK_JOB_REPO}@${SDK_JOB_BRANCH} (SDK job source)..."
    git clone --depth 1 --branch "${SDK_JOB_BRANCH}" "${SDK_JOB_REPO}" \
        "${SDK_JOB_DIR}" --quiet
fi
if [ ! -x "${SDK_JOB_DIR}/deploy/skill_evolution_job/deploy.sh" ]; then
    echo "ERROR: ${SDK_JOB_DIR}/deploy/skill_evolution_job/deploy.sh not found." >&2
    echo "Set SDK_JOB_DIR to an SDK checkout that has the job, or" >&2
    echo "SDK_JOB_REPO/SDK_JOB_BRANCH to a ref that carries it." >&2
    exit 1
fi

# Engine baked into the image. The job source branch ships upstream
# main's scripts/skill_evolution.py, which lacks the agentic-analyst and
# incumbent-guard kwargs this lab depends on (error_analyst_fn, tools,
# incumbent_score — SDK PR #395). The image must carry the same engine
# the lab pins for local runs (SDK_REPO@SDK_BRANCH in .env, the pair
# ensure_sdk.py clones), so clone that ref and hand its scripts/ to the
# SDK deploy.sh via --scripts-dir. SDK_ENGINE_DIR overrides with a local
# checkout.
SDK_ENGINE_REPO="${SDK_REPO:-https://github.com/evekhm/BigQuery-Agent-Analytics-SDK.git}"
SDK_ENGINE_BRANCH="${SDK_BRANCH:-lab-stable}"
if [ -z "${SDK_ENGINE_DIR:-}" ]; then
    SDK_ENGINE_DIR="$(mktemp -d)/sdk-engine"
    echo "Cloning ${SDK_ENGINE_REPO}@${SDK_ENGINE_BRANCH} (engine source)..."
    git clone --depth 1 --branch "${SDK_ENGINE_BRANCH}" "${SDK_ENGINE_REPO}" \
        "${SDK_ENGINE_DIR}" --quiet
fi
if ! grep -q 'error_analyst_fn' "${SDK_ENGINE_DIR}/scripts/skill_evolution.py"; then
    echo "ERROR: ${SDK_ENGINE_DIR}/scripts/skill_evolution.py has no error_analyst_fn;" >&2
    echo "the image would silently drop the agentic analysts and the incumbent guard." >&2
    echo "Point SDK_REPO/SDK_BRANCH (or SDK_ENGINE_DIR) at an engine that has them." >&2
    exit 1
fi

echo "========================================="
echo "  Deploying Skill Evolution (SDK job)"
echo "========================================="
echo "  Project:    $PROJECT_ID"
echo "  Region:     $REGION"
echo "  Job:        $JOB_NAME"
echo "  SDK source: ${SDK_JOB_REPO}@${SDK_JOB_BRANCH}"
echo "  Engine:     ${SDK_ENGINE_DIR}/scripts (${SDK_ENGINE_REPO}@${SDK_ENGINE_BRANCH})"
echo "  PR target:  ${GITHUB_REPO:-<none — dry-run mode>}"
echo "========================================="

# GITHUB_REPO / gh-secret omitted => the SDK job runs in dry-run mode
# (reports + artifacts, no PRs). EVOLUTION_SCHEDULE keeps the old
# cadence-override knob (e.g. "*/30 * * * *" for demos).
DEPLOY_ARGS=(
    --project "${PROJECT_ID}"
    --region "${REGION}"
    --dataset "${DATASET_ID:-agent_logs}"
    --table "${TABLE_ID:-agent_events}"
    --dataset-location "${DATASET_LOCATION:-us-central1}"
    --schedule "${EVOLUTION_SCHEDULE:-0 9 * * 1}"
    # Relative on purpose: the job resolves AGENT_REGISTRY inside its
    # runtime clone of this repo (registry.registry_path), not on this VM.
    --agent-registry eval/skill_evolution/agent_registry.json
    --extra-requirements "${PROJECT_ROOT}/eval/skill_evolution/sdk_job_requirements.txt"
    --scripts-dir "${SDK_ENGINE_DIR}/scripts"
    --gcs-bucket "${GCS_BUCKET:-${PROJECT_ID}-skill-evolution}"
    --smoke
)
if [ -n "${GITHUB_REPO:-}" ]; then
    DEPLOY_ARGS+=(--github-repo "${GITHUB_REPO}"
                  --gh-secret "${GH_SECRET_NAME:-github-pat}"
                  --base-branch "${GITHUB_BASE_BRANCH:-main}")
fi

bash "${SDK_JOB_DIR}/deploy/skill_evolution_job/deploy.sh" "${DEPLOY_ARGS[@]}" "$@"

# Lab wiring the generic job needs on every run (scheduled or manual):
# the hooks module (imported from the runtime clone of this repo), the
# SDK_REPO/SDK_BRANCH pair that ensure_sdk.py requires in-cloud (the
# scorer, the agentic analysts and the registry publish path all import
# through it), quality-report scoping to the lab's root agent, and the
# model IDs the hooks/engine read.
echo "Persisting lab hook wiring on job ${JOB_NAME}..."
gcloud run jobs update "${JOB_NAME}" \
    --project "${PROJECT_ID}" --region "${REGION}" \
    --update-env-vars "^|^EVOLUTION_HOOKS=eval.skill_evolution_hooks|SDK_REPO=${SDK_REPO:-https://github.com/evekhm/BigQuery-Agent-Analytics-SDK.git}|SDK_BRANCH=${SDK_BRANCH:-lab-stable}|QUALITY_APP_NAME=${QUALITY_APP_NAME:-knowledge_supervisor}|TRAFFIC_MODE=${TRAFFIC_MODE:-deployed}|MIN_SESSIONS=${MIN_SESSIONS:-20}|EVAL_QUESTIONS_FILE=${EVAL_QUESTIONS_FILE:-eval/data/questions/two_defect_evolve.json}|EVAL_MODEL_ID=${EVAL_MODEL_ID:-gemini-3.5-flash}|EVOLUTION_MODEL_ID=${EVOLUTION_MODEL_ID:-gemini-3.5-flash}|SKILL_EVOLUTION_MODEL_ID=${SKILL_EVOLUTION_MODEL_ID:-gemini-3.5-flash}|MODEL_LOCATION=${MODEL_LOCATION:-global}|GOOGLE_CLOUD_LOCATION=${GOOGLE_CLOUD_LOCATION:-global}" \
    --quiet

echo ""
echo "========================================="
echo "  Deployment complete!"
echo "========================================="
echo ""
echo "Run manually (weekly-equivalent, real PR when --github-repo was set):"
echo "  gcloud run jobs execute $JOB_NAME --project=$PROJECT_ID --region=$REGION"
echo ""
echo "Demo profile (13-question lite set, synthetic quality source):"
echo "  bash scripts/demo/skill_evolution/run_lite.sh"
echo ""
echo "Scheduled: ${EVOLUTION_SCHEDULE:-0 9 * * 1} (cron, UTC)"
echo "  gcloud scheduler jobs describe ${JOB_NAME}-cron --project=$PROJECT_ID --location=$REGION"
