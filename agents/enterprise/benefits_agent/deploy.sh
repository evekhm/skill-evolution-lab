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

# Deploy the Benefits agent as a Cloud Run A2A service. Mirrors the
# policy agent's deploy: the shared modules (skill_registry.py from the
# SDK, tools.py and skill_loader.py from policy_agent) are copied in for
# the build and removed afterwards — one source of truth in the repo.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_PATH="$SCRIPT_DIR/../../../.env"
if [ -f "$ENV_PATH" ]; then
    source "$ENV_PATH"
else
    echo "WARNING: .env file not found at $ENV_PATH"
fi

REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SDK_ROOT="${SDK_DIR:-$REPO_ROOT/.sdk/BigQuery-Agent-Analytics-SDK}"
SKILL_REGISTRY_SRC="$SDK_ROOT/examples/skill_evolution_lab/agent/skill_registry.py"
if [ ! -f "$SKILL_REGISTRY_SRC" ]; then
    echo "ERROR: skill_registry.py not found at $SKILL_REGISTRY_SRC"
    echo "Set SDK_DIR to a BigQuery-Agent-Analytics-SDK clone (branch main)."
    exit 1
fi

cp "$SKILL_REGISTRY_SRC" "$SCRIPT_DIR/skill_registry.py"
cp "$SCRIPT_DIR/../policy_agent/tools.py" "$SCRIPT_DIR/tools.py"
cp "$SCRIPT_DIR/../policy_agent/skill_loader.py" "$SCRIPT_DIR/skill_loader.py"
trap 'rm -f "$SCRIPT_DIR/skill_registry.py" "$SCRIPT_DIR/tools.py" "$SCRIPT_DIR/skill_loader.py"' EXIT

AGENT_REGISTRY_JSON="$REPO_ROOT/eval/skill_evolution/agent_registry.json"
BENEFITS_SKILL_ID=$(jq -r '.agents.benefits_agent.skill_id' "$AGENT_REGISTRY_JSON")
SKILL_REGISTRY_LOCATION=$(jq -r '.registry_location // "us-central1"' "$AGENT_REGISTRY_JSON")

adk deploy cloud_run --project=${PROJECT_ID} --region=${REGION} \
    --service_name=${BENEFITS_AGENT_SERVICE_NAME:-benefits-agent} \
    --a2a "${SCRIPT_DIR}"/ \
    -- --no-allow-unauthenticated --min-instances=1 --set-env-vars="DATASET_LOCATION=${DATASET_LOCATION},DATASET_ID=${DATASET_ID},TABLE_ID=${TABLE_ID},BENEFITS_AGENT_MODEL_ID=${BENEFITS_AGENT_MODEL_ID:-gemini-3.5-flash},REGION=${REGION},DEPLOY_COMMIT=${DEPLOY_COMMIT:-local},AGENT_VERSION=${AGENT_VERSION:-},SKILL_SOURCE=${SKILL_SOURCE:-registry},SKILL_REGISTRY_ID=${BENEFITS_SKILL_ID},SKILL_REGISTRY_LOCATION=${SKILL_REGISTRY_LOCATION}"
