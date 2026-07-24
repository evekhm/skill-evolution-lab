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

# Roll the demo back to V0: reset the skills to their V0 baselines and
# republish them to the Skill Registry as the latest revisions.
#
# The registry is append-only, so rollback = publishing V0 again on top;
# the evolved revisions stay in the registry history. Agents fetch the
# latest revision at startup, so the script restarts policy_agent and the
# supervisor by default so they serve V0 immediately.
#
# Usage:
#   bash scripts/demo/skill_evolution/rollback_demo.sh                # full rollback
#   bash scripts/demo/skill_evolution/rollback_demo.sh --baseline two-defect
#   bash scripts/demo/skill_evolution/rollback_demo.sh --skip-redeploy

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

set -a
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/.env"
set +a

BASELINE="two-defect"   # the production-loop demo's V0 (use "stub" for the bare V0)
SKIP_REDEPLOY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --baseline) BASELINE="$2"; shift 2 ;;
        --skip-redeploy) SKIP_REDEPLOY=true; shift ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done

echo "=== Rollback to V0 (baseline: ${BASELINE}) ==="

# Refuse to run while a local demo is executing: the demo rewrites the
# SKILL.md files this script publishes, so a concurrent rollback pushes
# whatever evolved skill the demo has deployed at that moment.
if pgrep -f "run_demo.sh" >/dev/null 2>&1; then
    echo "ERROR: a local demo run is executing (pgrep -f run_demo.sh)."
    echo "Wait for it to finish (it restores V0 itself), then rerun."
    exit 1
fi

# 1. Reset local skill files to V0.
# Copy from the committed SKILL.v0.md baselines — never git checkout:
# a checkout restores whatever HEAD holds, and HEAD once carried an
# evolved skill, which a later `seed` then republished as "V0".
echo "[1/4] Resetting SKILL.md files to V0..."
cp "${PROJECT_ROOT}/agents/enterprise/knowledge_supervisor/app/skill/SKILL.v0.md" \
   "${PROJECT_ROOT}/agents/enterprise/knowledge_supervisor/app/skill/SKILL.md"
cp "${PROJECT_ROOT}/agents/enterprise/benefits_agent/skill/SKILL.v0.md" \
   "${PROJECT_ROOT}/agents/enterprise/benefits_agent/skill/SKILL.md"

POLICY_SKILL_DIR="${PROJECT_ROOT}/agents/enterprise/policy_agent/skill"
if [ "${BASELINE}" = "two-defect" ]; then
    cp "${POLICY_SKILL_DIR}/SKILL.v0_two_defect.md" "${POLICY_SKILL_DIR}/SKILL.md"
else
    cp "${POLICY_SKILL_DIR}/SKILL.v0.md" "${POLICY_SKILL_DIR}/SKILL.md"
fi

# 2. Republish V0 to the Skill Registry (new latest revisions)
echo "[2/4] Publishing V0 to the Skill Registry..."
uv run python "${PROJECT_ROOT}/eval/skill_evolution/registry_sync.py" seed

# 3. Restart agents so they fetch the V0 revision
if [ "${SKIP_REDEPLOY}" = false ]; then
    echo "[3/4] Restarting policy_agent + knowledge_supervisor..."
    bash "${PROJECT_ROOT}/agents/enterprise/policy_agent/deploy.sh"
    bash "${PROJECT_ROOT}/agents/enterprise/knowledge_supervisor/deploy.sh"
else
    echo "[3/4] Skipped (--skip-redeploy): agents serve V0 after their next restart."
fi

# 4. Verify — by CONTENT, not by revision id: download the newest
# revision and check it is actually a V0 skill (a bad push still
# produces a fresh-looking revision id).
echo "[4/4] Verification (content of newest registry revision):"
for agent in policy_agent supervisor benefits_agent; do
    if ! uv run python "${PROJECT_ROOT}/eval/skill_evolution/registry_sync.py" \
            verify-read --agent "${agent}" | grep -q 'version: "0"'; then
        echo "ERROR: newest registry revision for ${agent} is NOT V0."
        exit 1
    fi
    echo "  ${agent}: newest revision content-verified V0"
done
if [ "${SKIP_REDEPLOY}" = false ]; then
    echo "  Registry-read log lines (may take ~1 min to appear):"
    sleep 60
    gcloud logging read 'textPayload:"Loaded skill from registry"' \
        --project="${PROJECT_ID}" --limit=4 --freshness=10m \
        --format="value(timestamp,textPayload)" || true
fi

echo ""
echo "=== Rollback complete: registry latest = V0; evolved revisions remain in history ==="
