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

# Deploy quality_agent as a Cloud Run Job with daily Cloud Scheduler trigger.

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

JOB_NAME="quality-agent"
IMAGE_NAME="$REGION-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/$JOB_NAME"

echo "========================================="
echo "  Deploying Quality Agent"
echo "========================================="
echo "  Project:  $PROJECT_ID"
echo "  Region:   $REGION"
echo "  Image:    $IMAGE_NAME"
echo "========================================="
echo ""

echo "[1/9] Building container image..."
# Copy files into build context:
#   - ensure_sdk.py: SDK discovery/import (quality_report.py shim uses it)
#   - eval/data/eval_spec.json: scope + ground truth + golden Q&A for the judge
#   - gcs_utils.py: shared GCS upload/download utilities
cp "${PROJECT_ROOT}/ensure_sdk.py" "${SCRIPT_DIR}/ensure_sdk.py"
cp "${PROJECT_ROOT}/agents/workflow/gcs_utils.py" "${SCRIPT_DIR}/gcs_utils.py"
mkdir -p "${SCRIPT_DIR}/eval/data"
cp "${PROJECT_ROOT}/eval/data/eval_spec.json" "${SCRIPT_DIR}/eval/data/" 2>/dev/null || true
cp "${PROJECT_ROOT}/eval/data/agent_context.json" "${SCRIPT_DIR}/eval/data/" 2>/dev/null || true
cp "${PROJECT_ROOT}/eval/data/quality_config.json" "${SCRIPT_DIR}/eval/data/" 2>/dev/null || true

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
rm -f "${SCRIPT_DIR}/ensure_sdk.py" "${SCRIPT_DIR}/gcs_utils.py"
rm -rf "${SCRIPT_DIR}/eval"
echo "  Done."

PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)' --quiet)
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "[2/9] Granting Secret Manager access (for github-pat secret)..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet > /dev/null
echo "  Done."

echo "[3/9] Granting Vertex AI User permission..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/aiplatform.user" \
    --quiet > /dev/null
echo "  Done."

echo "[4/9] Granting BigQuery User permission..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/bigquery.user" \
    --quiet > /dev/null
echo "  Done."

echo "[5/9] Granting Cloud Storage write permission..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/storage.objectCreator" \
    --quiet > /dev/null
echo "  Done."

echo "[6/9] Deploying Cloud Run Job..."
gcloud run jobs deploy "$JOB_NAME" \
  --image "$IMAGE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --task-timeout=600s \
  --max-retries=0 \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},REGION=${REGION},DATASET_ID=${DATASET_ID},DATASET_LOCATION=${DATASET_LOCATION},TABLE_ID=${TABLE_ID},GOOGLE_GENAI_USE_VERTEXAI=True,TIME_PERIOD=${TIME_PERIOD:-24h},DEPLOY_COMMIT=${DEPLOY_COMMIT:-local},GCS_BUCKET=${PROJECT_ID}-skill-evolution,GCS_UPLOAD=true,AGENT_VERSION=${AGENT_VERSION:-}" \
  --set-secrets="GH_TOKEN=github-pat:latest" \
  --quiet || { echo "ERROR: job deploy failed"; exit 1; }
echo "  Done."

# --- Cloud Scheduler (daily at 8am UTC) ---
SCHEDULER_JOB="quality-agent-daily"
SCHEDULER_SA="${SERVICE_ACCOUNT}"

echo "[7/9] Enabling Cloud Scheduler API..."
gcloud services enable cloudscheduler.googleapis.com --project="$PROJECT_ID" --quiet
echo "  Done."

echo "[8/9] Granting Cloud Run Invoker role..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SCHEDULER_SA}" \
    --role="roles/run.invoker" \
    --quiet > /dev/null
echo "  Done."

echo "[9/9] Creating Cloud Scheduler (daily at 08:00 UTC)..."
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

if gcloud scheduler jobs describe "$SCHEDULER_JOB" --project="$PROJECT_ID" --location="$REGION" >/dev/null 2>&1; then
    echo "  Updating existing scheduler job..."
    gcloud scheduler jobs update http "$SCHEDULER_JOB" \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --schedule="0 8 * * *" \
        --uri="$JOB_URI" \
        --http-method=POST \
        --oauth-service-account-email="$SCHEDULER_SA" \
        --quiet
else
    echo "  Creating scheduler job..."
    gcloud scheduler jobs create http "$SCHEDULER_JOB" \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --schedule="0 8 * * *" \
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
echo "Override time period:"
echo "  gcloud run jobs execute $JOB_NAME --project=$PROJECT_ID --region=$REGION --update-env-vars='TIME_PERIOD=1h'"
echo ""
echo "Scheduled: daily at 08:00 UTC (analyzes last 24h)"
echo "  gcloud scheduler jobs describe $SCHEDULER_JOB --project=$PROJECT_ID --location=$REGION"

cd "${ORIG_DIR}"
