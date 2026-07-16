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

# local_start.sh - Start all agents locally for testing.
#
# Launches policy_agent and hr_calculator as local A2A servers, then
# starts the knowledge_supervisor with the ADK web UI. Sub-agent URLs
# are overridden to point at localhost so no GCP deployment is needed.
#
# Prerequisites:
#   - Run scripts/local/local_setup.sh first
#
# Usage:
#   bash scripts/local/local_start.sh          # starts all agents
#   bash scripts/local/local_start.sh stop     # kills all agents

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
AGENTS_DIR="${PROJECT_ROOT}/agents"
LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}"

if [ "$1" = "stop" ]; then
    echo "Stopping local agents..."
    pkill -f "adk api_server.*--port 8080" 2>/dev/null || true
    pkill -f "adk api_server.*--port 8081" 2>/dev/null || true
    pkill -f "adk web.*--port 8000" 2>/dev/null || true
    echo "Done."
    exit 0
fi

# Source .env from project root
if [ -f "${PROJECT_ROOT}/.env" ]; then
    source "${PROJECT_ROOT}/.env"
else
    echo "ERROR: .env not found at ${PROJECT_ROOT}/.env"
    echo "Run: bash scripts/local/local_setup.sh"
    exit 1
fi

# Override sub-agent URLs to point at local servers
export POLICY_AGENT_URL="http://localhost:8080"
export HR_CALCULATOR_URL="http://localhost:8081"

cd "${PROJECT_ROOT}"

# --- Start sub-agents as A2A servers ---
# adk api_server expects AGENTS_DIR where each subdir has agent.py + __init__.py

echo "=== Starting policy_agent on port 8080 (A2A) ==="
uv run adk api_server --a2a --port 8080 --host 0.0.0.0 "${AGENTS_DIR}" \
    > "${LOG_DIR}/policy_agent_local.log" 2>&1 &
POLICY_PID=$!
echo "  PID: ${POLICY_PID} | Log: ${LOG_DIR}/policy_agent_local.log"

echo "=== Starting hr_calculator on port 8081 (A2A) ==="
uv run adk api_server --a2a --port 8081 --host 0.0.0.0 "${AGENTS_DIR}" \
    > "${LOG_DIR}/hr_calculator_local.log" 2>&1 &
HR_PID=$!
echo "  PID: ${HR_PID} | Log: ${LOG_DIR}/hr_calculator_local.log"

# Wait for sub-agents to be ready
echo "Waiting for sub-agents to start..."
for i in {1..10}; do
    if curl -s http://localhost:8080/ >/dev/null 2>&1 && \
       curl -s http://localhost:8081/ >/dev/null 2>&1; then
        echo "  Sub-agents ready."
        break
    fi
    sleep 1
done

# --- Start supervisor with web UI ---
echo "=== Starting knowledge_supervisor web UI on port 8000 ==="
uv run adk web --port 8000 --host 0.0.0.0 "${AGENTS_DIR}" \
    > "${LOG_DIR}/supervisor_local.log" 2>&1 &
SUP_PID=$!
echo "  PID: ${SUP_PID} | Log: ${LOG_DIR}/supervisor_local.log"

sleep 3

echo ""
echo "============================================"
echo "  Local test environment is running!"
echo "============================================"
echo "  Supervisor Web UI:  http://localhost:8000"
echo "  Policy Agent A2A:   http://localhost:8080"
echo "  HR Calculator A2A:  http://localhost:8081"
echo ""
echo "  Logs: ${LOG_DIR}/"
echo "  Stop: bash scripts/local/local_start.sh stop"
echo "============================================"
echo ""
echo "Tailing supervisor log (Ctrl+C to stop tailing, agents keep running):"
tail -f "${LOG_DIR}/supervisor_local.log"
