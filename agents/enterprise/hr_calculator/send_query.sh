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

# Send a test query to the deployed hr_calculator via A2A JSON-RPC.
#
# Usage:
#   ./agents/enterprise/hr_calculator/test.sh                                    # default question
#   ./agents/enterprise/hr_calculator/test.sh -q "How many PTO days do I have?"  # custom question

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
fi

PROJECT="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${HR_CALCULATOR_SERVICE_NAME:-hr-calculator}"

# Parse arguments
QUERY="How many PTO days do I have left this year?"
while [[ $# -gt 0 ]]; do
    case "$1" in
        -q|--query)
            QUERY="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 [-q \"your question\"]"
            exit 1
            ;;
    esac
done

# Discover Cloud Run URL
echo "=========================================="
echo "  TARGET PROJECT: ${PROJECT_ID}"
echo "  MODE: DEPLOYED (Cloud Run A2A service)"
echo "=========================================="
echo "Discovering ${SERVICE_NAME} in ${PROJECT}/${REGION}..."
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --project="$PROJECT" --region="$REGION" \
    --format="value(status.url)" 2>/dev/null)

if [ -z "$SERVICE_URL" ]; then
    echo "ERROR: Could not find Cloud Run service '${SERVICE_NAME}'!"
    exit 1
fi
echo "Service URL: ${SERVICE_URL}"

# Get identity token for authenticated Cloud Run
TOKEN=$(gcloud auth print-identity-token 2>/dev/null)

# Verify agent card is served
echo ""
echo "Checking A2A agent card..."
CARD=$(curl -s -H "Authorization: Bearer $TOKEN" \
    "${SERVICE_URL}/a2a/hr_calculator/.well-known/agent-card.json")

if echo "$CARD" | jq -e '.name' > /dev/null 2>&1; then
    echo "  Agent: $(echo "$CARD" | jq -r '.name')"
    echo "  Skills: $(echo "$CARD" | jq -r '[.skills[].name] | join(", ")')"
else
    echo "ERROR: Agent card not found! Response:"
    echo "$CARD"
    exit 1
fi

# Send A2A message/send request
echo ""
echo "─────────────────────────────────────────"
echo "Q: ${QUERY}"
echo "─────────────────────────────────────────"

TASK_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
MSG_ID=$(python3 -c "import uuid; print(uuid.uuid4())")

T0=$(date +%s.%N)
RESPONSE=$(curl -s -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    "${SERVICE_URL}/a2a/hr_calculator" \
    -d "{
        \"jsonrpc\": \"2.0\",
        \"id\": \"${MSG_ID}\",
        \"method\": \"message/send\",
        \"params\": {
            \"message\": {
                \"messageId\": \"${MSG_ID}\",
                \"role\": \"user\",
                \"parts\": [{\"kind\": \"text\", \"text\": \"${QUERY}\"}]
            }
        }
    }")

# Extract the text response
echo "$RESPONSE" | jq -r '
    .result.artifacts[]?.parts[]?.text //
    .result.status.message.parts[]?.text //
    .error.message //
    "No text in response"
' 2>/dev/null || echo "$RESPONSE"
T1=$(date +%s.%N)
LATENCY=$(awk "BEGIN{printf \"%.1f\", ${T1}-${T0}}")
echo ""
echo "Latency: ${LATENCY}s"
