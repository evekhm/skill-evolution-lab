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

# Script to deploy policy_agent to Cloud Run via A2A

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

# Skill Registry client: copied next to skill_loader.py so registry mode
# (SKILL_SOURCE=registry) can resolve it inside the container.
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SDK_ROOT="${SDK_DIR:-$REPO_ROOT/.sdk/BigQuery-Agent-Analytics-SDK}"
SKILL_REGISTRY_SRC="$SDK_ROOT/examples/skill_evolution_lab/agent/skill_registry.py"
if [ ! -f "$SKILL_REGISTRY_SRC" ]; then
    echo "ERROR: skill_registry.py not found at $SKILL_REGISTRY_SRC"
    echo "Set SDK_DIR to a BigQuery-Agent-Analytics-SDK clone (branch main)."
    exit 1
fi
cp "$SKILL_REGISTRY_SRC" "$SCRIPT_DIR/skill_registry.py"
trap 'rm -f "$SCRIPT_DIR/skill_registry.py"' EXIT

AGENT_REGISTRY_JSON="$REPO_ROOT/eval/skill_evolution/agent_registry.json"
POLICY_SKILL_ID=$(jq -r '.agents.policy_agent.skill_id' "$AGENT_REGISTRY_JSON")
SKILL_REGISTRY_LOCATION=$(jq -r '.registry_location // "us-central1"' "$AGENT_REGISTRY_JSON")

# AGENT_VERSION default is EMPTY so BQ custom_tags.agent_version follows the
# SKILL.md frontmatter (the registry revision), never a stale literal.
adk deploy cloud_run --project=${PROJECT_ID} --region=${REGION} \
    --service_name=${POLICY_AGENT_SERVICE_NAME} \
    --a2a "${SCRIPT_DIR}"/ \
    -- --no-allow-unauthenticated --min-instances=1 --set-env-vars="DATASET_LOCATION=${DATASET_LOCATION},DATASET_ID=${DATASET_ID},TABLE_ID=${TABLE_ID},POLICY_AGENT_MODEL_ID=${POLICY_AGENT_MODEL_ID},REGION=${REGION},DEPLOY_COMMIT=${DEPLOY_COMMIT:-local},POLICY_VERTEX_PROMPT_ID=${POLICY_VERTEX_PROMPT_ID:-},AGENT_VERSION=${AGENT_VERSION:-},SKILL_SOURCE=${SKILL_SOURCE:-registry},SKILL_REGISTRY_ID=${POLICY_SKILL_ID},SKILL_REGISTRY_LOCATION=${SKILL_REGISTRY_LOCATION}"
