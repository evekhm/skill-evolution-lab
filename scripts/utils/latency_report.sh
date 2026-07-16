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

# Trace latency analyzer — shows a timing tree for agent sessions.
#
# Usage:
#   bash scripts/utils/latency_report.sh                        # latest trace
#   bash scripts/utils/latency_report.sh --limit 5              # last 5 traces
#   bash scripts/utils/latency_report.sh --session <session_id>  # specific session
#   bash scripts/utils/latency_report.sh --time-period 1h        # traces from last hour
#   bash scripts/utils/latency_report.sh --app-name my_agent     # filter by agent app
#   bash scripts/utils/latency_report.sh --verbose               # show questions/responses
#   bash scripts/utils/latency_report.sh --no-stitch             # skip A2A stitching

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Load .env
if [ -f "${PROJECT_ROOT}/.env" ]; then
    set -a
    source "${PROJECT_ROOT}/.env"
    set +a
else
    echo "ERROR: .env not found at ${PROJECT_ROOT}/.env"
    exit 1
fi

# Validate required env vars
for var in PROJECT_ID DATASET_ID TABLE_ID DATASET_LOCATION; do
    if [ -z "${!var}" ]; then
        echo "ERROR: $var is not set in .env"
        exit 1
    fi
done

cd "${PROJECT_ROOT}"
uv run python3 scripts/utils/latency_report.py "$@"
