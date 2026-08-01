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

# Deploy all agents to GCP.
#
# Deploys all 7 components in sequence:
#   1. policy_agent            -> Cloud Run (A2A)
#   2. hr_calculator           -> Cloud Run (A2A)
#   3. benefits_agent          -> Cloud Run (A2A)
#   4. knowledge_supervisor    -> Vertex AI Agent Engine
#   5. traffic_generator       -> Cloud Run Job
#   6. quality_agent           -> Cloud Run Job + Cloud Scheduler (daily)
#   7. skill_evolution_agent   -> Cloud Run Job + Cloud Scheduler (weekly)
#
# Prerequisites:
#   - .env configured with PROJECT_ID and other settings
#   - GCP project set up (run scripts/setup/setup_gcp.sh first)
#
# Usage: bash scripts/deploy/deploy_gcp.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/deploy_$(date +%Y%m%d_%H%M%S).log"

# Tee all output (stdout + stderr) to log file, with timestamps
exec > >(while IFS= read -r line; do printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$line"; done | tee -a "$LOG_FILE") 2>&1

TOTAL_STEPS=7

echo "========================================="
echo "  Agent Quality Lab -- Deploy All"
echo "  Log: ${LOG_FILE}"
echo "========================================="

DEPLOY_START=$(date +%s)

if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
else
    echo "WARNING: .env file not found at $PROJECT_ROOT/.env"
fi

FAILED=()

# Deploy policy_agent A2A to Cloud Run
echo ""
echo "========================================="
echo "[1/${TOTAL_STEPS}] Deploying policy_agent..."
echo "========================================="
STEP_START=$(date +%s)
if (cd "$PROJECT_ROOT/agents/enterprise/policy_agent" && ./deploy.sh); then
    echo "[1/${TOTAL_STEPS}] policy_agent: SUCCESS ($(( $(date +%s) - STEP_START ))s)"
else
    echo "[1/${TOTAL_STEPS}] policy_agent: FAILED ($(( $(date +%s) - STEP_START ))s)"
    FAILED+=("policy_agent")
fi

# Deploy hr_calculator A2A to Cloud Run
echo ""
echo "========================================="
echo "[2/${TOTAL_STEPS}] Deploying hr_calculator..."
echo "========================================="
STEP_START=$(date +%s)
if (cd "$PROJECT_ROOT/agents/enterprise/hr_calculator" && ./deploy.sh); then
    echo "[2/${TOTAL_STEPS}] hr_calculator: SUCCESS ($(( $(date +%s) - STEP_START ))s)"
else
    echo "[2/${TOTAL_STEPS}] hr_calculator: FAILED ($(( $(date +%s) - STEP_START ))s)"
    FAILED+=("hr_calculator")
fi

# Deploy benefits_agent A2A to Cloud Run. Must precede the supervisor:
# the supervisor discovers the benefits-agent Cloud Run URL and silently
# runs WITHOUT a benefits tool when the service is absent — on a fresh
# project that broke local/deployed topology parity unnoticed.
echo ""
echo "========================================="
echo "[3/${TOTAL_STEPS}] Deploying benefits_agent..."
echo "========================================="
STEP_START=$(date +%s)
if (cd "$PROJECT_ROOT/agents/enterprise/benefits_agent" && ./deploy.sh); then
    echo "[3/${TOTAL_STEPS}] benefits_agent: SUCCESS ($(( $(date +%s) - STEP_START ))s)"
else
    echo "[3/${TOTAL_STEPS}] benefits_agent: FAILED ($(( $(date +%s) - STEP_START ))s)"
    FAILED+=("benefits_agent")
fi

# Deploy knowledge_supervisor to Agent Engine
echo ""
echo "========================================="
echo "[4/${TOTAL_STEPS}] Deploying knowledge_supervisor..."
echo "========================================="
STEP_START=$(date +%s)
if (cd "$PROJECT_ROOT/agents/enterprise/knowledge_supervisor" && ./deploy.sh); then
    echo "[4/${TOTAL_STEPS}] knowledge_supervisor: SUCCESS ($(( $(date +%s) - STEP_START ))s)"
else
    echo "[4/${TOTAL_STEPS}] knowledge_supervisor: FAILED ($(( $(date +%s) - STEP_START ))s)"
    FAILED+=("knowledge_supervisor")
fi

# Deploy Traffic Generator as Cloud Run Job
echo ""
echo "========================================="
echo "[5/${TOTAL_STEPS}] Deploying traffic_generator..."
echo "========================================="
STEP_START=$(date +%s)
if (cd "$PROJECT_ROOT/agents/workflow/traffic_generator" && ./deploy.sh); then
    echo "[5/${TOTAL_STEPS}] traffic_generator: SUCCESS ($(( $(date +%s) - STEP_START ))s)"
else
    echo "[5/${TOTAL_STEPS}] traffic_generator: FAILED ($(( $(date +%s) - STEP_START ))s)"
    FAILED+=("traffic_generator")
fi

# Deploy Quality Agent as Cloud Run Job + Cloud Scheduler
echo ""
echo "========================================="
echo "[6/${TOTAL_STEPS}] Deploying quality_agent..."
echo "========================================="
STEP_START=$(date +%s)
if (cd "$PROJECT_ROOT/agents/workflow/quality_agent" && ./deploy.sh); then
    echo "[6/${TOTAL_STEPS}] quality_agent: SUCCESS ($(( $(date +%s) - STEP_START ))s)"
else
    echo "[6/${TOTAL_STEPS}] quality_agent: FAILED ($(( $(date +%s) - STEP_START ))s)"
    FAILED+=("quality_agent")
fi

# Deploy Skill Evolution Agent as Cloud Run Job + Cloud Scheduler
echo ""
echo "========================================="
echo "[7/${TOTAL_STEPS}] Deploying skill_evolution_agent..."
echo "========================================="
STEP_START=$(date +%s)
if (cd "$PROJECT_ROOT/agents/workflow/skill_evolution_agent" && ./deploy.sh); then
    echo "[7/${TOTAL_STEPS}] skill_evolution_agent: SUCCESS ($(( $(date +%s) - STEP_START ))s)"
else
    echo "[7/${TOTAL_STEPS}] skill_evolution_agent: FAILED ($(( $(date +%s) - STEP_START ))s)"
    FAILED+=("skill_evolution_agent")
fi

TOTAL_ELAPSED=$(( $(date +%s) - DEPLOY_START ))
TOTAL_MIN=$(( TOTAL_ELAPSED / 60 ))
TOTAL_SEC=$(( TOTAL_ELAPSED % 60 ))

echo ""
echo "========================================="
if [ ${#FAILED[@]} -eq 0 ]; then
    echo "All deployments complete!"
else
    echo "FAILED deployments: ${FAILED[*]}"
fi
echo "Total time: ${TOTAL_MIN}m ${TOTAL_SEC}s"
echo "Full log: ${LOG_FILE}"
echo "========================================="

[ ${#FAILED[@]} -eq 0 ]
