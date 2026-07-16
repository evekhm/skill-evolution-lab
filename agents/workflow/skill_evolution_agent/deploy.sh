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

# Deploy skill_evolution_agent as a Cloud Run Job with weekly scheduler.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
ENV_PATH="${PROJECT_ROOT}/.env"
ORIG_DIR="$(pwd)"

if [ -f "${ENV_PATH}" ]; then
    source "${ENV_PATH}"
else
    echo "Warning: .env file not found at ${ENV_PATH}"
fi

cd "${SCRIPT_DIR}"

JOB_NAME="skill-evolution-agent"
IMAGE_NAME="$REGION-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/$JOB_NAME"

echo "========================================="
echo "  Deploying Skill Evolution Agent"
echo "========================================="
echo "  Project:  $PROJECT_ID"
echo "  Region:   $REGION"
echo "  Image:    $IMAGE_NAME"
echo "========================================="
echo ""

echo "[1/5] Building container image..."
# Copy shared modules into build context
mkdir -p "${SCRIPT_DIR}/eval/data" \
         "${SCRIPT_DIR}/eval/scoring" \
         "${SCRIPT_DIR}/eval/data/questions" \
         "${SCRIPT_DIR}/eval/skill_evolution"

# Eval module
cp "${PROJECT_ROOT}/eval/eval_cases.py" "${SCRIPT_DIR}/eval/"
cp "${PROJECT_ROOT}/eval/data/eval_cases.json" "${SCRIPT_DIR}/eval/data/"
cp "${PROJECT_ROOT}/eval/data/eval_spec.json" "${SCRIPT_DIR}/eval/data/" 2>/dev/null || true
cp "${PROJECT_ROOT}/eval/data/agent_context.json" "${SCRIPT_DIR}/eval/data/" 2>/dev/null || true
cp "${PROJECT_ROOT}/eval/data/golden_evals.json" "${SCRIPT_DIR}/eval/data/" 2>/dev/null || true

# Agent registry (required — pipeline can't discover agents without it)
if [ ! -f "${PROJECT_ROOT}/eval/skill_evolution/agent_registry.json" ]; then
    echo "ERROR: agent_registry.json not found at ${PROJECT_ROOT}/eval/skill_evolution/"
    exit 1
fi
cp "${PROJECT_ROOT}/eval/skill_evolution/agent_registry.json" "${SCRIPT_DIR}/eval/skill_evolution/"
# Skill Registry sync CLI (push_skill_to_registry + manual ops in the container)
cp "${PROJECT_ROOT}/eval/skill_evolution/registry_sync.py" "${SCRIPT_DIR}/eval/skill_evolution/"

# Quality scorer + SDK discovery + shared utilities
cp "${PROJECT_ROOT}/eval/scoring/score_conversations.py" "${SCRIPT_DIR}/eval/scoring/"
cp "${PROJECT_ROOT}/ensure_sdk.py" "${SCRIPT_DIR}/ensure_sdk.py"
cp "${PROJECT_ROOT}/agents/workflow/gcs_utils.py" "${SCRIPT_DIR}/gcs_utils.py"
touch "${SCRIPT_DIR}/eval/__init__.py" "${SCRIPT_DIR}/eval/scoring/__init__.py"

# Questions for traffic generation (required — traffic generator needs them)
if ! ls "${PROJECT_ROOT}/eval/data/questions/"*.json >/dev/null 2>&1; then
    echo "ERROR: No question files found in ${PROJECT_ROOT}/eval/data/questions/"
    exit 1
fi
cp "${PROJECT_ROOT}/eval/data/questions/"*.json "${SCRIPT_DIR}/eval/data/questions/"

# Traffic generator
cp -r "${PROJECT_ROOT}/agents/workflow/traffic_generator" "${SCRIPT_DIR}/traffic_generator"

# Enterprise agents (for local mode traffic generation)
cp -r "${PROJECT_ROOT}/agents/enterprise" "${SCRIPT_DIR}/enterprise"

# Quality agent (BigQuery-sourced pre-flight reuses run_quality_report)
cp -r "${PROJECT_ROOT}/agents/workflow/quality_agent" "${SCRIPT_DIR}/quality_agent"

# SDK source comes from .env — abort rather than bake a default into the image.
if [ -z "${SDK_REPO:-}" ] || [ -z "${SDK_BRANCH:-}" ]; then
    echo "ERROR: SDK_REPO and SDK_BRANCH must be set in .env (see .env.example)."
    exit 1
fi

# Async submit + poll (see scripts/deploy/submit_build.sh: synchronous
# builds submit exits non-zero under WIF creds even on successful builds).
bash "${PROJECT_ROOT}/scripts/deploy/submit_build.sh" \
  --project "$PROJECT_ID" \
  --config "${PROJECT_ROOT}/scripts/deploy/cloudbuild_job.yaml" \
  --substitutions="_IMAGE=${IMAGE_NAME},_SDK_REPO=${SDK_REPO},_SDK_BRANCH=${SDK_BRANCH}" \
  . || { echo "ERROR: image build failed"; exit 1; }

# Clean up copied files
rm -rf "${SCRIPT_DIR}/eval" "${SCRIPT_DIR}/traffic_generator" \
       "${SCRIPT_DIR}/enterprise" "${SCRIPT_DIR}/quality_agent" \
       "${SCRIPT_DIR}/ensure_sdk.py" "${SCRIPT_DIR}/gcs_utils.py"
echo "  Done."

PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)' --quiet)
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "[2/5] Granting permissions..."
for role in roles/aiplatform.user roles/storage.admin roles/secretmanager.secretAccessor; do
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="$role" \
        --quiet > /dev/null
done
echo "  Done."

# Target repo for automatic PRs; derived from the checkout's origin unless set.
if [ -z "${GITHUB_REPO:-}" ]; then
    GITHUB_REPO=$(git -C "${PROJECT_ROOT}" remote get-url origin 2>/dev/null \
        | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')
fi
echo "  PR target repo: ${GITHUB_REPO:-<none>}"

echo "[3/5] Deploying Cloud Run Job..."
# AGENT_VERSION default is EMPTY so BQ tags follow SKILL.md frontmatter.
gcloud run jobs deploy "$JOB_NAME" \
  --image "$IMAGE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --task-timeout=14400s \
  --max-retries=0 \
  --memory=2Gi \
  --set-secrets="GH_TOKEN=github-pat:latest" \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},REGION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=True,FULL_LOOP=true,GCS_BUCKET=${PROJECT_ID}-skill-evolution,GCS_UPLOAD=true,GITHUB_BASE_BRANCH=${GITHUB_BASE_BRANCH:-main},AGENT_REGISTRY=/app/eval/skill_evolution/agent_registry.json,AGENT_VERSION=${AGENT_VERSION:-},TRAFFIC_MODE=${TRAFFIC_MODE:-deployed},QUALITY_SOURCE=${QUALITY_SOURCE:-bigquery},MIN_SESSIONS=${MIN_SESSIONS:-20},GITHUB_REPO=${GITHUB_REPO},SUPERVISOR_DISPLAY_NAME=${SUPERVISOR_DISPLAY_NAME:-knowledge-supervisor},DATASET_ID=${DATASET_ID},DATASET_LOCATION=${DATASET_LOCATION},TABLE_ID=${TABLE_ID},EVAL_QUESTIONS_FILE=${EVAL_QUESTIONS_FILE:-/app/eval/data/questions/two_defect_evolve.json},EVAL_TIME_PERIOD=${EVAL_TIME_PERIOD:-6h}" \
  --quiet || { echo "ERROR: job deploy failed"; exit 1; }
echo "  Done."

# --- Cloud Scheduler (weekly on Mondays at 09:00 UTC) ---
SCHEDULER_JOB="skill-evolution-weekly"
SCHEDULER_SA="${SERVICE_ACCOUNT}"

echo "[4/5] Enabling Cloud Scheduler API..."
gcloud services enable cloudscheduler.googleapis.com --project="$PROJECT_ID" --quiet
echo "  Done."

# Cadence override for demos (e.g. EVOLUTION_SCHEDULE="*/30 * * * *").
EVOLUTION_SCHEDULE="${EVOLUTION_SCHEDULE:-0 9 * * 1}"

echo "[5/5] Creating Cloud Scheduler (schedule: ${EVOLUTION_SCHEDULE})..."
echo "  Granting Cloud Run Invoker role..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SCHEDULER_SA}" \
    --role="roles/run.invoker" \
    --quiet > /dev/null
echo "  Role granted."

JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

if gcloud scheduler jobs describe "$SCHEDULER_JOB" --project="$PROJECT_ID" --location="$REGION" >/dev/null 2>&1; then
    echo "  Updating existing scheduler job..."
    gcloud scheduler jobs update http "$SCHEDULER_JOB" \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --schedule="${EVOLUTION_SCHEDULE}" \
        --uri="$JOB_URI" \
        --http-method=POST \
        --oauth-service-account-email="$SCHEDULER_SA" \
        --quiet
else
    echo "  Creating scheduler job..."
    gcloud scheduler jobs create http "$SCHEDULER_JOB" \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --schedule="${EVOLUTION_SCHEDULE}" \
        --uri="$JOB_URI" \
        --http-method=POST \
        --oauth-service-account-email="$SCHEDULER_SA" \
        --quiet
fi
echo "  Done."

echo ""
echo "========================================="
echo "  Deployment complete!"
echo "========================================="
echo ""
echo "Run manually:"
echo "  gcloud run jobs execute $JOB_NAME --project=$PROJECT_ID --region=$REGION"
echo ""
echo "Scheduled: ${EVOLUTION_SCHEDULE} (cron, UTC)"
echo "  gcloud scheduler jobs describe $SCHEDULER_JOB --project=$PROJECT_ID --location=$REGION"

cd "${ORIG_DIR}"
