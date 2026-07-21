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

# Run a load test from this machine against the deployed Reasoning Engine.
#
# Usage:
#   bash run.sh                                          # default topics
#   bash run.sh --generate-only -o questions.json        # generate questions only
#   bash run.sh --from-file questions.json               # replay saved questions
#   bash run.sh --topics "pto:5,benefits:3" --duration 2 # custom topics, 2 min

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_PATH="${SCRIPT_DIR}/../../../.env"

if [ -f "${ENV_PATH}" ]; then
    source "${ENV_PATH}"
fi

# Defaults (overridable via env vars or CLI flags)
export TOPICS_CONFIG=${TOPICS_CONFIG:-'pto:3,benefits:2,expenses:2,holidays:2,sick_leave:2'}
export CONCURRENCY=${CONCURRENCY:-3}
export DURATION_MINUTES=${DURATION_MINUTES:-5}
export PYTHONPATH="${SCRIPT_DIR}/../../..:${PYTHONPATH}"

cd "${SCRIPT_DIR}/../../.."
python3 agents/workflow/traffic_generator/main.py "$@"
