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

# Trigger the deployed Quality Agent Cloud Run Job.
#
# Usage:
#   ./agents/workflow/quality_agent/run_job.sh              # analyze last 24h (default)
#   TIME_PERIOD=1h ./agents/workflow/quality_agent/run_job.sh   # analyze last 1h
#   TIME_PERIOD=7d ./agents/workflow/quality_agent/run_job.sh   # analyze last 7 days

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_PATH="${SCRIPT_DIR}/../../../.env"

if [ -f "${ENV_PATH}" ]; then
    source "${ENV_PATH}"
fi

JOB_NAME="quality-agent"
TIME_PERIOD=${TIME_PERIOD:-24h}

echo "Triggering Quality Agent job..."
echo "  Project:     $PROJECT_ID"
echo "  Region:      $REGION"
echo "  Time period: $TIME_PERIOD"
echo ""

gcloud run jobs execute "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --update-env-vars="TIME_PERIOD=${TIME_PERIOD}"
