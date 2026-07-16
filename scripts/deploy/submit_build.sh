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

# Submit a Cloud Build asynchronously and poll it to completion.
#
# Why: synchronous `gcloud builds submit` insists on streaming logs from the
# default logs bucket and requires project Viewer/Owner for that — under
# Workload Identity Federation creds (GitHub Actions) it exits non-zero even
# when the build SUCCEEDS. Submitting with --async and polling GetBuild only
# needs roles/cloudbuild.builds.editor, so the exit code reflects the actual
# build result.
#
# Usage (all remaining args are passed to `gcloud builds submit`):
#   submit_build.sh --project PROJECT_ID --tag IMAGE .
#   submit_build.sh --project PROJECT_ID --config cloudbuild.yaml --substitutions=... .

set -euo pipefail

PROJECT=""
ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project) PROJECT="$2"; shift 2 ;;
        --project=*) PROJECT="${1#--project=}"; shift ;;
        *) ARGS+=("$1"); shift ;;
    esac
done
[ -n "$PROJECT" ] || { echo "ERROR: submit_build.sh needs --project"; exit 1; }

BUILD_ID=$(gcloud builds submit "${ARGS[@]}" \
    --project="$PROJECT" --async --format='value(id)') || {
    echo "ERROR: build submission failed"
    exit 1
}
[ -n "$BUILD_ID" ] || { echo "ERROR: no build id returned"; exit 1; }

echo "  Build ${BUILD_ID} submitted; polling until done..."
for _ in $(seq 1 120); do
    sleep 10
    STATUS=$(gcloud builds describe "$BUILD_ID" --project="$PROJECT" \
        --format='value(status)' 2>/dev/null || echo "UNKNOWN")
    case "$STATUS" in
        SUCCESS)
            echo "  Build ${BUILD_ID}: SUCCESS"
            exit 0 ;;
        FAILURE|CANCELLED|TIMEOUT|EXPIRED|INTERNAL_ERROR)
            echo "ERROR: build ${BUILD_ID} finished with status ${STATUS}."
            echo "Logs: https://console.cloud.google.com/cloud-build/builds/${BUILD_ID}?project=${PROJECT}"
            exit 1 ;;
    esac
done
echo "ERROR: build ${BUILD_ID} did not finish within 20 minutes."
exit 1
