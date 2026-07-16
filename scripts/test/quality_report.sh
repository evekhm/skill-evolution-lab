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

# Run the quality evaluation report.
#
# Usage:
#   bash scripts/test/quality_report.sh                     # evaluate last 100 sessions
#   bash scripts/test/quality_report.sh --time-period 1h    # last 1 hour
#   bash scripts/test/quality_report.sh --time-period 1d    # last 24 hours
#   bash scripts/test/quality_report.sh --no-eval           # browse Q&A only
#   bash scripts/test/quality_report.sh --report            # also generate markdown
#   bash scripts/test/quality_report.sh --output-json r.json # structured JSON output
#   bash scripts/test/quality_report.sh --limit 50          # evaluate 50 sessions
#   bash scripts/test/quality_report.sh --samples all       # show all sessions
#   bash scripts/test/quality_report.sh --threshold 5       # warn above 5% unhelpful

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
uv run python3 agents/workflow/quality_agent/quality_report.py "$@"
