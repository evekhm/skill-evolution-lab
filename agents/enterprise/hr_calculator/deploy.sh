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

# Script to deploy hr_calculator agent to Cloud Run via A2A

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ENV_PATH="$SCRIPT_DIR/../../../.env"
if [ -f "$ENV_PATH" ]; then
    source "$ENV_PATH"
else
    echo "WARNING: .env file not found at $ENV_PATH"
fi

# Get project number for service account
PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format="value(projectNumber)" --quiet)
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "Ensuring Storage Object Viewer permission for Cloud Build..."
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/storage.objectViewer" --quiet

echo "Ensuring Artifact Registry Writer permission for Cloud Build..."
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/artifactregistry.writer" --quiet

echo "Ensuring Logs Writer permission for Cloud Build..."
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/logging.logWriter" --quiet

echo "Ensuring Vertex AI User permission for Cloud Run..."
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/aiplatform.user" --quiet

adk deploy cloud_run --project=${PROJECT_ID} --region=${REGION} \
    --service_name=${HR_CALCULATOR_SERVICE_NAME} \
    --a2a "${SCRIPT_DIR}"/ \
    -- --no-allow-unauthenticated --min-instances=1 --set-env-vars="DATASET_LOCATION=${DATASET_LOCATION},DATASET_ID=${DATASET_ID},TABLE_ID=${TABLE_ID},HR_CALCULATOR_MODEL_ID=${HR_CALCULATOR_MODEL_ID},HR_CALCULATOR_LOCATION=${REGION},DEPLOY_COMMIT=${DEPLOY_COMMIT:-local},AGENT_VERSION=${AGENT_VERSION:-0}"
