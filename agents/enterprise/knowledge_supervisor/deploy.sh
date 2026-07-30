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

# Script to deploy knowledge-supervisor agent to Agent Engine.
#
# Uses `adk deploy agent_engine` to upload code and create/update the
# Reasoning Engine. ADK wraps the agent in AdkApp which exposes
# stream_query via the :streamQuery endpoint (used by Gemini Enterprise).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_PATH="${SCRIPT_DIR}/../../../.env"

if [ -f "${ENV_PATH}" ]; then
    echo "Sourcing .env file from project root..."
    source "${ENV_PATH}"
else
    echo "Warning: .env file not found at ${ENV_PATH}"
fi

echo "Using Project: ${PROJECT_ID}"

if [ -f "${SCRIPT_DIR}/requirements.txt" ]; then
    echo "Using existing requirements.txt..."
else
    echo "Exporting dependencies using uv..."
    uv export --no-hashes --no-header --no-dev --no-emit-project --no-annotate > "${SCRIPT_DIR}/requirements.txt"
fi

echo "Discovering policy_agent URL..."
DISCOVERED_POLICY_URL=$(gcloud run services describe "$POLICY_AGENT_SERVICE_NAME" \
  --platform managed --region "$REGION" --project="${PROJECT_ID}" \
  --format='value(status.url)')
[ -n "$DISCOVERED_POLICY_URL" ] || { echo "ERROR: Failed to discover policy_agent URL!"; exit 1; }
echo "Policy Agent URL: $DISCOVERED_POLICY_URL"

echo "Discovering hr_calculator URL..."
DISCOVERED_HR_URL=$(gcloud run services describe "$HR_CALCULATOR_SERVICE_NAME" \
  --platform managed --region "$REGION" --project="${PROJECT_ID}" \
  --format='value(status.url)')
[ -n "$DISCOVERED_HR_URL" ] || { echo "ERROR: Failed to discover hr_calculator URL!"; exit 1; }
echo "HR Calculator URL: $DISCOVERED_HR_URL"

# Registry mode support: the Agent Engine package contains ONLY app/, so the
# shared skill parser and the SkillRegistry client must travel inside it.
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
SDK_ROOT="${SDK_DIR:-$REPO_ROOT/.sdk/BigQuery-Agent-Analytics-SDK}"
SKILL_REGISTRY_SRC="$SDK_ROOT/examples/skill_evolution_lab/agent/skill_registry.py"
if [ ! -f "$SKILL_REGISTRY_SRC" ]; then
    echo "ERROR: skill_registry.py not found at $SKILL_REGISTRY_SRC"
    echo "Set SDK_DIR to a BigQuery-Agent-Analytics-SDK clone (branch fix/md-scorecards)."
    exit 1
fi
cp "$REPO_ROOT/agents/enterprise/policy_agent/skill_loader.py" "${SCRIPT_DIR}/app/skill_loader.py"
cp "$SKILL_REGISTRY_SRC" "${SCRIPT_DIR}/app/skill_registry.py"
trap 'rm -f "${SCRIPT_DIR}/app/skill_loader.py" "${SCRIPT_DIR}/app/skill_registry.py"' EXIT

AGENT_REGISTRY_JSON="$REPO_ROOT/eval/skill_evolution/agent_registry.json"
SUPERVISOR_SKILL_ID=$(jq -r '.agents.supervisor.skill_id' "$AGENT_REGISTRY_JSON")
SKILL_REGISTRY_LOCATION=$(jq -r '.registry_location // "us-central1"' "$AGENT_REGISTRY_JSON")

# Create temporary env file with resolved values.
# Agent Engine rejects env vars with EMPTY values (400 INVALID_ARGUMENT:
# "Required field is not set"), so optional vars are written only when set.
ENV_TMP="${SCRIPT_DIR}/.env.deploy"
cat > "${ENV_TMP}" <<ENVEOF
PROJECT_ID="${PROJECT_ID}"
SUPERVISOR_MODEL_ID="${SUPERVISOR_MODEL_ID:-gemini-2.5-pro}"
MODEL_LOCATION="${MODEL_LOCATION:-us-central1}"
SUPERVISOR_REGION="${SUPERVISOR_REGION:-us-central1}"
SUPERVISOR_DISPLAY_NAME="${SUPERVISOR_DISPLAY_NAME:-knowledge-supervisor}"
POLICY_AGENT_URL="${DISCOVERED_POLICY_URL}"
POLICY_AGENT_SERVICE_NAME="${POLICY_AGENT_SERVICE_NAME:-policy-agent}"
HR_CALCULATOR_URL="${DISCOVERED_HR_URL}"
HR_CALCULATOR_SERVICE_NAME="${HR_CALCULATOR_SERVICE_NAME:-hr-calculator}"
DATASET_ID="${DATASET_ID}"
DATASET_LOCATION="${DATASET_LOCATION}"
TABLE_ID="${TABLE_ID}"
DEPLOY_COMMIT="${DEPLOY_COMMIT:-local}"
SKILL_SOURCE="${SKILL_SOURCE:-registry}"
SKILL_REGISTRY_ID="${SUPERVISOR_SKILL_ID}"
SKILL_REGISTRY_LOCATION="${SKILL_REGISTRY_LOCATION}"
GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true
ENVEOF
# Stamp the deployed code version into every BQ event (TRACE_LABELS
# merges into custom_tags) so evolution selectors can pin traces to a
# specific deployment. User-provided TRACE_LABELS are appended after.
GIT_SHA=$(git -C "${SCRIPT_DIR}" rev-parse --short HEAD 2>/dev/null || echo "unknown")
SW_LABELS="sw_version=${GIT_SHA}"
if [ -n "${TRACE_LABELS:-}" ]; then
    SW_LABELS="${SW_LABELS},${TRACE_LABELS}"
fi
echo "TRACE_LABELS=\"${SW_LABELS}\"" >> "${ENV_TMP}"

for optional_var in SUPERVISOR_VERTEX_PROMPT_ID POLICY_VERTEX_PROMPT_ID AGENT_VERSION; do
    value="${!optional_var:-}"
    if [ -n "${value}" ]; then
        echo "${optional_var}=\"${value}\"" >> "${ENV_TMP}"
    fi
done

echo "Resolved .env.deploy contents:"
cat "${ENV_TMP}"

# IAM grants for compute SA
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo "Granting BigQuery roles to ${SERVICE_ACCOUNT}..."
for role in roles/bigquery.dataEditor roles/bigquery.user roles/bigquery.jobUser; do
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${SERVICE_ACCOUNT}" --role="$role" --quiet > /dev/null
done

# Remove __pycache__ before packaging
find "${SCRIPT_DIR}/app" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

REGION=${SUPERVISOR_REGION:-"us-central1"}
TOKEN=$(gcloud auth print-access-token)

echo "Searching for existing Reasoning Engine..."
RESPONSE=$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines")
REASONING_ENGINE_ID=$(echo "$RESPONSE" | jq -r '.reasoningEngines[]? | select(.displayName == "knowledge-supervisor") | .name' | head -n 1)

# Deploy via ADK (handles packaging, upload, dependency resolution)
echo ""
echo "========================================="
echo "Deploying source code via ADK"
echo "========================================="
# adk deploy prints "Deploy failed: ..." but can still exit 0 — capture the
# output and treat that line as a failure too.
ADK_LOG=$(mktemp)
if [ -n "$REASONING_ENGINE_ID" ]; then
    echo "Found existing Reasoning Engine: $REASONING_ENGINE_ID"
    echo "Updating existing Reasoning Engine..."
    adk deploy agent_engine \
        --project="${PROJECT_ID}" \
        --region="${REGION}" \
        --display_name="knowledge-supervisor" \
        --adk_app_object="app" \
        --env_file="${ENV_TMP}" \
        --requirements_file="${SCRIPT_DIR}/requirements.txt" \
        --agent_engine_id="${REASONING_ENGINE_ID}" \
        "${SCRIPT_DIR}/app" 2>&1 | tee "${ADK_LOG}"
    ADK_EXIT=${PIPESTATUS[0]}
else
    echo "No existing Reasoning Engine found."
    echo "Deploying to NEW Agent Engine..."
    adk deploy agent_engine \
        --project="${PROJECT_ID}" \
        --region="${REGION}" \
        --display_name="knowledge-supervisor" \
        --adk_app_object="app" \
        --env_file="${ENV_TMP}" \
        --requirements_file="${SCRIPT_DIR}/requirements.txt" \
        "${SCRIPT_DIR}/app" 2>&1 | tee "${ADK_LOG}"
    ADK_EXIT=${PIPESTATUS[0]}
fi

rm -f "${ENV_TMP}"

if [ $ADK_EXIT -ne 0 ] || grep -q "Deploy failed" "${ADK_LOG}"; then
    # One known false negative: the ADK CLI sometimes reports
    # "Deploy failed: [Errno 2] ... app_tmp<ts>" about its own
    # already-removed temp folder AFTER the engine update succeeded.
    # Treat that as success when the success marker is present; fail
    # on every other "Deploy failed".
    if grep -qE "(Updated|Created) agent engine" "${ADK_LOG}" \
       && grep -qE "Deploy failed: \[Errno 2\].*app_tmp" "${ADK_LOG}" \
       && [ "$(grep -c "Deploy failed" "${ADK_LOG}")" -eq 1 ]; then
        echo "NOTE: engine updated; ignoring ADK's post-success temp-folder cleanup error."
    else
        rm -f "${ADK_LOG}"
        echo "ERROR: ADK deployment failed!"
        exit 1
    fi
fi
rm -f "${ADK_LOG}"

# Re-discover the engine ID (needed for new deploys and for the summary)
TOKEN=$(gcloud auth print-access-token)
RESPONSE=$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines")
REASONING_ENGINE_ID=$(echo "$RESPONSE" | jq -r '.reasoningEngines[]? | select(.displayName == "knowledge-supervisor") | .name' | head -n 1)

echo ""
echo "Deployment completed."

# Grant IAM to Reasoning Engine SA
REASONING_SA="service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
echo ""
echo "Granting IAM roles to Reasoning Engine SA: ${REASONING_SA}..."
# aiplatform.user covers Skill Registry reads (GetSkill) for SKILL_SOURCE=registry.
for role in roles/bigquery.dataEditor roles/bigquery.user roles/bigquery.jobUser roles/aiplatform.user; do
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${REASONING_SA}" --role="$role" --quiet > /dev/null
done

for svc in "${POLICY_AGENT_SERVICE_NAME}" "${HR_CALCULATOR_SERVICE_NAME}"; do
    echo "  Cloud Run Invoker on ${svc}..."
    gcloud run services add-iam-policy-binding "${svc}" \
        --member="serviceAccount:${REASONING_SA}" \
        --role="roles/run.invoker" --region="${REGION}" --project="${PROJECT_ID}" --quiet > /dev/null
done

echo "Reasoning Engine SA IAM grants complete."

echo ""
echo "========================================="
echo "Deployment Summary"
echo "========================================="
echo "  Agent Engine ID: ${REASONING_ENGINE_ID}"
echo ""
echo "  Use this ID when connecting Gemini Enterprise:"
echo "    ${REASONING_ENGINE_ID}"
echo ""
echo "  Smoke test:"
echo "    bash scripts/test/smoke_test_deployed.sh"
echo "========================================="
