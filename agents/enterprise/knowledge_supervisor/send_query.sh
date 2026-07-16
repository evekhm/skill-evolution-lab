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

# Send a test query to the deployed knowledge_supervisor via Agent Engine.
#
# Discovers the Reasoning Engine by display name and sends a question
# via the REST API. Wrapper around scripts/test/smoke_test_deployed.sh.
#
# Usage:
#   ./agents/enterprise/knowledge_supervisor/test.sh                              # default questions
#   ./agents/enterprise/knowledge_supervisor/test.sh -q "How many PTO days left?" # custom query

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

exec bash "$PROJECT_ROOT/scripts/test/smoke_test_deployed.sh" "$@"
