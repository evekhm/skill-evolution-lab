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

# Script to deploy the load test agent as a Cloud Run Job

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_PATH="${SCRIPT_DIR}/../../../.env"
PWD=`(pwd)`

# Source .env file if it exists in project root
if [ -f "${ENV_PATH}" ]; then
    source "${ENV_PATH}"
else
    echo "Warning: .env file not found at ${ENV_PATH}"
fi

# Navigate to agent directory for build
cd "${SCRIPT_DIR}"

JOB_NAME="knowledge-supervisor-test"
IMAGE_NAME="$REGION-docker.pkg.dev/$PROJECT_ID/cloud-run-source-deploy/load-test-job"

echo "Building image with Cloud Build..."
echo "Project: $PROJECT_ID"
echo "Image: $IMAGE_NAME"

# Async submit + poll (see scripts/deploy/submit_build.sh: synchronous
# builds submit exits non-zero under WIF creds even on successful builds).
bash "${SCRIPT_DIR}/../../../scripts/deploy/submit_build.sh" \
  --project "$PROJECT_ID" --tag "$IMAGE_NAME" . \
  || { echo "ERROR: image build failed"; exit 1; }

# Generate resolved env file to avoid quoting issues
cat <<EOF > resolved_env.yaml
PROJECT_ID: "$PROJECT_ID"
REGION: "$REGION"
CONCURRENCY: "${CONCURRENCY}"
DURATION_MINUTES: "${DURATION_MINUTES}"
TOPICS_CONFIG: "${TOPICS_CONFIG}"
DEPLOY_COMMIT: "${DEPLOY_COMMIT:-local}"
AGENT_VERSION: "${AGENT_VERSION:-0}"
EOF

# Timeout = DURATION_MINUTES + 10min buffer (for question generation + in-flight queries)
TIMEOUT_SECONDS=$(( (${DURATION_MINUTES:-60} + 10) * 60 ))

gcloud run jobs deploy "$JOB_NAME" \
  --image "$IMAGE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --task-timeout="${TIMEOUT_SECONDS}s" \
  --max-retries=0 \
  --env-vars-file=resolved_env.yaml || { rm resolved_env.yaml; echo "ERROR: job deploy failed"; exit 1; }

rm resolved_env.yaml

echo "Deployment complete. You can run the job using:"
echo "gcloud run jobs execute $JOB_NAME --project=$PROJECT_ID --region=$REGION"
echo ""
echo "To override parameters on the fly:"
echo "gcloud run jobs execute $JOB_NAME --project=$PROJECT_ID --region=$REGION --update-env-vars=\"TOPICS_CONFIG='pto:5,benefits:5',CONCURRENCY=5\""

cd "${PWD}"
