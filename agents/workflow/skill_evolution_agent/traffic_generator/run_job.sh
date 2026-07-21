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

# Trigger the deployed Cloud Run Job to run a load test.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_PATH="${SCRIPT_DIR}/../../../.env"

if [ -f "${ENV_PATH}" ]; then
    source "${ENV_PATH}"
fi

DURATION_MINUTES=${DURATION_MINUTES:-60}
TIMEOUT_SECONDS=$(( (DURATION_MINUTES + 10) * 60 ))

gcloud run jobs execute knowledge-supervisor-test \
  --project=$PROJECT_ID \
  --region=$REGION \
  --task-timeout="${TIMEOUT_SECONDS}s" \
  --update-env-vars="^|^CONCURRENCY=${CONCURRENCY:-10}|DURATION_MINUTES=${DURATION_MINUTES}|TOPICS_CONFIG=${TOPICS_CONFIG:-pto:10,benefits:10,expenses:10,holidays:10,sick_leave:10}"
