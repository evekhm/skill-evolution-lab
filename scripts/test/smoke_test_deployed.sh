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

# smoke_test_deployed.sh - Smoke test the deployed knowledge-supervisor.
#
# Discovers the Reasoning Engine by display name and sends a question
# via the REST API. Useful for quick smoke tests after deployment.
#
# Usage:
#   bash scripts/test/smoke_test_deployed.sh                              # default test queries
#   bash scripts/test/smoke_test_deployed.sh -q "How many PTO days left?" # custom query

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [ -f "${PROJECT_ROOT}/.env" ]; then
    source "${PROJECT_ROOT}/.env"
fi

PROJECT="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
LOCATION="${SUPERVISOR_REGION:-us-central1}"
DISPLAY_NAME="knowledge-supervisor"
echo "=========================================="
echo "  TARGET PROJECT: ${PROJECT}"
echo "=========================================="

# Parse arguments
QUERY=""
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

# Discover Reasoning Engine by display name
echo "Discovering Reasoning Engine '${DISPLAY_NAME}' in ${PROJECT}/${LOCATION}..."
TOKEN=$(gcloud auth print-access-token)
RESPONSE=$(curl -s -H "Authorization: Bearer ${TOKEN}" \
    "https://${LOCATION}-aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/${LOCATION}/reasoningEngines")

ENGINE_ID=$(echo "$RESPONSE" | jq -r ".reasoningEngines[]? | select(.displayName == \"${DISPLAY_NAME}\") | .name" | head -n 1)

if [ -z "$ENGINE_ID" ]; then
    echo "ERROR: No Reasoning Engine found with display name '${DISPLAY_NAME}'!"
    exit 1
fi
echo "Found: ${ENGINE_ID}"
echo ""

send_query() {
    local q="$1"
    echo "─────────────────────────────────────────"
    echo "Q: ${q}"
    echo "─────────────────────────────────────────"
    # AdkApp wrapping exposes stream_query via the :streamQuery endpoint.
    # Gemini Enterprise also uses this endpoint (widgetStreamAssist).
    local payload
    payload=$(jq -n --arg q "$q" '{
        class_method: "stream_query",
        input: {message: $q, user_id: "test_user"}
    }')

    local start_ts=$(date +%s%N)
    local result
    result=$(curl -s --max-time 120 -X POST \
         -H "Authorization: Bearer ${TOKEN}" \
         -H "Content-Type: application/json" \
         "https://${LOCATION}-aiplatform.googleapis.com/v1/${ENGINE_ID}:streamQuery" \
         -d "$payload" 2>&1)
    local end_ts=$(date +%s%N)
    local elapsed_ms=$(( (end_ts - start_ts) / 1000000 ))

    # Check for API errors (single JSON object = error)
    local error
    error=$(echo "$result" | head -1 | jq -r '.error.message // empty' 2>/dev/null)
    if [ -n "$error" ]; then
        echo "  ERROR: ${error}"
        local elapsed_s=$(awk "BEGIN{printf \"%.1f\", ${elapsed_ms}/1000}")
        echo "  Latency: ${elapsed_s}s"
        echo ""
        return
    fi

    # Parse the streaming response (newline-delimited JSON) into a summary
    local summary
    summary=$(printf '%s' "$result" | jq -rs '
        # Supervisor event (first line)
        (.[0] // {}) as $sup |
        # Sub-agent response (last line with text)
        ([.[] | select(.content?.parts[]?.text?)] | last // {}) as $resp |
        # A2A metadata from sub-agent
        ($resp.custom_metadata // {}) as $meta |
        ($meta["a2a:response"] // {}) as $a2a |

        # Extract fields
        {
          model: ($sup.model_version // "?"),
          routed_to: ([.[] | .content?.parts[]? | .function_call?.args?.agent_name? // empty | select(. != "")] | first // null),
          answer: ([.[] | .content?.parts[]? | .text? // empty | select(. != "")] | last // null),
          supervisor_tokens: {
            prompt: ($sup.usage_metadata?.prompt_token_count // null),
            output: ($sup.usage_metadata?.candidates_token_count // null),
            thinking: ($sup.usage_metadata?.thoughts_token_count // null)
          },
          sub_agent_tokens: {
            prompt: ($a2a.metadata?.adk_usage_metadata?.promptTokenCount // null),
            output: ($a2a.metadata?.adk_usage_metadata?.candidatesTokenCount // null),
            thinking: ($a2a.metadata?.adk_usage_metadata?.thoughtsTokenCount // null)
          },
          tools_called: ([($a2a.history // [])[]?.parts[]? | select(.kind == "data" and .data.args) | .data.name] | unique | join(", ")),
          task_status: ($a2a.status?.state // null)
        }
    ' 2>/dev/null)

    local answer=$(echo "$summary" | jq -r '.answer // empty')
    local routed_to=$(echo "$summary" | jq -r '.routed_to // empty')

    if [ -n "$answer" ]; then
        echo "$summary" | jq -r '
          "  Routed to:  \(.routed_to // "direct")",
          "  Model:      \(.model)",
          "  Tools:      \(if .tools_called == "" then "(none)" else .tools_called end)",
          "  Tokens:     supervisor \(.supervisor_tokens.prompt // 0)→\(.supervisor_tokens.output // 0) (thinking: \(.supervisor_tokens.thinking // 0))",
          "              sub-agent  \(.sub_agent_tokens.prompt // 0)→\(.sub_agent_tokens.output // 0) (thinking: \(.sub_agent_tokens.thinking // 0))",
          "",
          "  A: \(.answer)"
        '
    elif [ -n "$routed_to" ]; then
        echo "  Routed to: ${routed_to}"
        echo "  (streaming response incomplete — agent routed but no final answer received)"
        echo "  Try again; this can happen when the Agent Engine instance is warming up."
    else
        echo "  (no response received)"
    fi

    echo ""
    local elapsed_s=$(awk "BEGIN{printf \"%.1f\", ${elapsed_ms}/1000}")
    echo "  Latency: ${elapsed_s}s"
    echo ""
}

if [ -n "$QUERY" ]; then
    send_query "$QUERY"
else
    send_query "What is our PTO policy?"
    send_query "How many PTO days do I have left?"
fi
