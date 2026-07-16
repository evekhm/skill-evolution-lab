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

# setup_gcp.sh - One-time GCP project setup.
#
# Enables required APIs, creates BigQuery dataset for agent analytics,
# creates Artifact Registry repo, and grants IAM roles to service accounts.
#
# Prerequisites:
#   - .env configured with PROJECT_ID
#   - gcloud authenticated with project owner/editor permissions
#
# Usage: bash scripts/setup/setup_gcp.sh

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/setup_$(date +%Y%m%d_%H%M%S).log"

# Tee all output (stdout + stderr) to log file
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================================="
echo "    Setup Script for Skill Evolution Lab                  "
echo "    Log: ${LOG_FILE}"
echo "=========================================================="

# 1. Configuration Check
if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
else
    echo "ERROR: .env file not found at $PROJECT_ROOT/.env"
    echo "Please copy .env.example to .env and fill in your settings."
    exit 1
fi

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "your-project-id" ]; then
    echo "ERROR: PROJECT_ID not set. Please edit .env with your GCP project."
    exit 1
fi

REGION=${REGION:-"us-central1"}
BQ_LOCATION=${DATASET_LOCATION:-"us-central1"}
DATASET_ID=${DATASET_ID:-"agent_logs"}

echo "Project ID:          $PROJECT_ID"
echo "Region:              $REGION"
echo "BQ Location:         $BQ_LOCATION"
echo "BQ Dataset:          $DATASET_ID"
echo "----------------------------------------------------------"

# 2. Enable required GCP APIs
APIS=(
  "aiplatform.googleapis.com"            # Vertex AI (Agent Engine, models)
  "artifactregistry.googleapis.com"      # Container image storage
  "cloudbuild.googleapis.com"            # Building containers
  "run.googleapis.com"                   # Cloud Run (sub-agents, load test)
  "iam.googleapis.com"                   # IAM permissions
  "cloudresourcemanager.googleapis.com"  # Project management
  "bigquery.googleapis.com"              # BigQuery Agent Analytics
  "logging.googleapis.com"               # Cloud Logging
  "storage.googleapis.com"               # Cloud Storage
)

echo ""
echo "Enabling required GCP APIs..."
for API in "${APIS[@]}"; do
  echo "  Enabling $API..."
  gcloud services enable "$API" --project "${PROJECT_ID}" --async
  if [ $? -ne 0 ]; then
    echo "  -> ERROR: Failed to submit enablement request for $API."
    exit 1
  fi
done

echo "Waiting for API enablement to propagate (10 seconds)..."
sleep 10

# 3. Create BigQuery Dataset (for Agent Analytics Plugin)
echo ""
echo "Creating BigQuery Dataset (if it doesn't exist)..."
if [ -n "$DATASET_ID" ]; then
    bq show --dataset "${PROJECT_ID}:${DATASET_ID}" >/dev/null 2>&1 || {
        echo "  Dataset ${DATASET_ID} not found. Creating..."
        bq mk --location="${BQ_LOCATION}" --dataset "${PROJECT_ID}:${DATASET_ID}"
    }
    echo "  Dataset ${DATASET_ID} ready."
else
    echo "  WARNING: DATASET_ID not set. Skipping dataset creation."
fi

# 4. Create Artifact Registry repository for Cloud Run source deploys
echo ""
echo "Creating Artifact Registry repository (if it doesn't exist)..."
if gcloud artifacts repositories describe cloud-run-source-deploy \
    --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "  Repository cloud-run-source-deploy already exists."
else
    echo "  Creating cloud-run-source-deploy repository..."
    gcloud artifacts repositories create cloud-run-source-deploy \
        --repository-format=docker \
        --location="${REGION}" \
        --project="${PROJECT_ID}" \
        --quiet
    echo "  Repository created."
fi

# 5. Set up IAM permissions for the default compute service account
echo ""
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "Setting up IAM permissions for ${SERVICE_ACCOUNT}..."

# BigQuery permissions (for Agent Analytics Plugin)
for ROLE in "roles/bigquery.dataEditor" "roles/bigquery.user" "roles/bigquery.jobUser"; do
  echo "  Granting $ROLE..."
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
      --member="serviceAccount:${SERVICE_ACCOUNT}" \
      --role="$ROLE" \
      --quiet
done

# Cloud Run / Build permissions
for ROLE in "roles/storage.objectViewer" "roles/artifactregistry.writer" "roles/logging.logWriter" "roles/aiplatform.user"; do
  echo "  Granting $ROLE..."
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
      --member="serviceAccount:${SERVICE_ACCOUNT}" \
      --role="$ROLE" \
      --quiet
done

# 6. Reasoning Engine service account permissions
REASONING_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
echo ""
echo "Setting up IAM permissions for Reasoning Engine SA: ${REASONING_SA}..."
for ROLE in "roles/bigquery.dataEditor" "roles/bigquery.user" "roles/bigquery.jobUser"; do
  echo "  Granting $ROLE..."
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
      --member="serviceAccount:${REASONING_SA}" \
      --role="$ROLE" \
      --quiet 2>/dev/null || echo "  (SA may not exist yet -- will be created on first Agent Engine deploy)"
done

# 7. Create GCS bucket for skill evolution run data (if configured)
GCS_BUCKET="${GCS_BUCKET:-${PROJECT_ID}-skill-evolution}"
echo ""
echo "Creating GCS bucket for skill evolution (if it doesn't exist)..."
if gsutil ls -b "gs://${GCS_BUCKET}" >/dev/null 2>&1; then
    echo "  Bucket gs://${GCS_BUCKET} already exists."
else
    echo "  Creating gs://${GCS_BUCKET}..."
    gsutil mb -l "${REGION}" -p "${PROJECT_ID}" "gs://${GCS_BUCKET}"
    echo "  Bucket created."
fi

# 8. Seed the Skill Registry with the current (V0) skills
echo ""
echo "Seeding Skill Registry..."
if uv run python "${PROJECT_ROOT}/eval/skill_evolution/registry_sync.py" seed; then
    echo "  Skill Registry seeded (idempotent: unchanged skills are skipped)."
else
    echo "  WARNING: Skill Registry seeding failed. You can retry with:"
    echo "    python eval/skill_evolution/registry_sync.py seed"
fi

echo ""
echo "=========================================================="
echo "Setup Complete!"
echo ""
echo "Full log: ${LOG_FILE}"
echo ""
echo "Next steps:"
echo "  1. Review .env settings"
echo "  2. Set up GitHub integration: bash scripts/setup/setup_github.sh"
echo "  3. Deploy everything: bash scripts/deploy/deploy_gcp.sh"
echo "=========================================================="
