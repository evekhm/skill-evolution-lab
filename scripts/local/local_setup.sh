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

# local_setup.sh - Set up the local Python environment for running agents.
#
# Syncs dependencies with uv, verifies GCP authentication, and tests
# that all agent modules import correctly. Run this before local_start.sh.
#
# Prerequisites:
#   - .env configured with PROJECT_ID
#   - uv installed (https://docs.astral.sh/uv/)
#   - gcloud authenticated
#
# Usage: bash scripts/local/local_setup.sh

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

echo "=== Setting up local environment ==="

# 1. Check .env exists
if [ ! -f "${PROJECT_ROOT}/.env" ]; then
    echo "ERROR: .env not found. Copy .env.example to .env and fill in your settings."
    exit 1
fi
source "${PROJECT_ROOT}/.env"

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "your-project-id" ]; then
    echo "ERROR: PROJECT_ID not set in .env"
    exit 1
fi

# 2. Check uv is installed
if ! command -v uv &>/dev/null; then
    echo "ERROR: uv not found. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# 3. Sync project dependencies
echo "Syncing Python dependencies with uv..."
cd "${PROJECT_ROOT}"
uv sync

# 4. Verify GCP auth
echo "Checking GCP authentication..."
if ! gcloud auth print-access-token &>/dev/null; then
    echo "ERROR: Not authenticated with GCP. Run: gcloud auth login"
    exit 1
fi

ACTIVE_PROJECT=$(gcloud config get-value project 2>/dev/null)
echo "  Active GCP project: ${ACTIVE_PROJECT}"
echo "  .env PROJECT_ID:    ${PROJECT_ID}"

# 5. Verify agent imports
echo ""
echo "Verifying agent imports..."
FAIL=0

echo -n "  policy_agent... "
if uv run python -c "from agents.enterprise.policy_agent.agent import root_agent" 2>/dev/null; then
    echo "OK"
else
    echo "FAIL"
    FAIL=1
fi

echo -n "  hr_calculator... "
if uv run python -c "from agents.enterprise.hr_calculator.agent import root_agent" 2>/dev/null; then
    echo "OK"
else
    echo "FAIL"
    FAIL=1
fi

echo -n "  knowledge_supervisor... "
if uv run python -c "from agents.enterprise.knowledge_supervisor.app.agent import root_agent" 2>/dev/null; then
    echo "OK"
else
    echo "FAIL"
    FAIL=1
fi

if [ $FAIL -ne 0 ]; then
    echo ""
    echo "ERROR: Some agents failed to import. Fix the errors above before running local_test.sh"
    exit 1
fi

echo ""
echo "=== Local environment ready ==="
echo "Run: bash scripts/local/local_start.sh"
