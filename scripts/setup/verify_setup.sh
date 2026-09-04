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

# verify_setup.sh — the 12 setup checks (README Prerequisites, section 5), scripted.
#
# Read-only: verifies tools, auth, .env, deployments, registry, and CI
# wiring. Prints PASS/FAIL per check; exit code = number of failures.
#
# Usage: bash scripts/setup/verify_setup.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

PASS=0
FAIL=0

ok()   { echo "[PASS] $1"; PASS=$((PASS+1)); }
bad()  { echo "[FAIL] $1"; [ -n "${2:-}" ] && echo "       -> $2"; FAIL=$((FAIL+1)); }

# --- 1 tools ---
missing=""
for t in gcloud gh uv bq jq; do command -v "$t" >/dev/null || missing="$missing $t"; done
if [ -z "$missing" ]; then ok "1 tools: gcloud gh uv bq jq"; else bad "1 tools" "missing:$missing"; fi

# --- 2 GCP auth + ADC ---
acct=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | head -1)
if [ -n "$acct" ] && gcloud auth application-default print-access-token >/dev/null 2>&1; then
    ok "2 GCP auth + ADC ($acct)"
else
    bad "2 GCP auth + ADC" "run: gcloud auth login && gcloud auth application-default login"
fi

# --- 3 GitHub auth ---
if gh auth status >/dev/null 2>&1; then ok "3 GitHub CLI auth"; else bad "3 GitHub CLI auth" "run: gh auth login"; fi

# --- 4 .env ---
if [ -f .env ]; then
    set -a; source .env; set +a
    if [ -n "${PROJECT_ID:-}" ] && [ "${PROJECT_ID}" != "your-project-id" ] && [ "${PROJECT_ID}" != "<YOUR_PROJECT_ID>" ]; then
        ok "4 .env (PROJECT_ID=${PROJECT_ID}, REGION=${REGION:-unset}, DATASET=${DATASET_ID:-unset}.${TABLE_ID:-unset})"
    else
        bad "4 .env" "PROJECT_ID not set — edit .env"
    fi
else
    bad "4 .env" "missing — cp .env.example .env and set PROJECT_ID"
fi
REGION="${REGION:-us-central1}"

# --- 5 local Python env ---
if uv run python -c "import agents.workflow.traffic_generator.main" >/dev/null 2>&1; then
    ok "5 local Python env (agent modules import)"
else
    bad "5 local Python env" "run: bash scripts/local/local_setup.sh"
fi

# --- 6 Cloud Run services ---
svcs=$(gcloud run services list --project="$PROJECT_ID" --region="$REGION" \
    --format="value(metadata.name,status.conditions[0].status)" 2>/dev/null)
for s in policy-agent hr-calculator; do
    if echo "$svcs" | grep -q "^${s}[[:space:]]*True$"; then
        ok "6 Cloud Run service: $s"
    else
        bad "6 Cloud Run service: $s" "deploy: bash scripts/deploy/deploy_gcp.sh"
    fi
done

# --- 7 Agent Engine supervisor (discovery only, no query) ---
TOKEN=$(gcloud auth print-access-token 2>/dev/null)
DISPLAY="${SUPERVISOR_DISPLAY_NAME:-knowledge-supervisor}"
engines=$(curl -s -H "Authorization: Bearer ${TOKEN}" \
    "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines" \
    | jq -r --arg d "$DISPLAY" '.reasoningEngines[]? | select(.displayName==$d) | .name' | head -1)
if [ -n "$engines" ]; then
    ok "7 Agent Engine supervisor (${engines##*/})"
else
    bad "7 Agent Engine supervisor" "'${DISPLAY}' not found — deploy the supervisor"
fi

# --- 8 jobs + schedulers ---
jobs=$(gcloud run jobs list --project="$PROJECT_ID" --region="$REGION" --format="value(metadata.name)" 2>/dev/null)
for j in quality-agent bqaa-skill-evolution; do
    if echo "$jobs" | grep -q "^${j}$"; then ok "8 Cloud Run job: $j"; else bad "8 Cloud Run job: $j"; fi
done
scheds=$(gcloud scheduler jobs list --project="$PROJECT_ID" --location="$REGION" --format="value(name)" 2>/dev/null)
if echo "$scheds" | grep -q "quality-agent-daily" && echo "$scheds" | grep -q "bqaa-skill-evolution-cron"; then
    ok "8 schedulers: quality-agent-daily + bqaa-skill-evolution-cron"
else
    bad "8 schedulers" "expected quality-agent-daily and bqaa-skill-evolution-cron"
fi

# --- 9 Skill Registry seeded ---
if uv run python eval/skill_evolution/registry_sync.py revisions --agent policy_agent 2>/dev/null | grep -q "revision"; then
    ok "9 Skill Registry seeded (policy_agent has revisions)"
else
    bad "9 Skill Registry" "seed: bash scripts/setup/setup_gcp.sh (or registry_sync.py seed)"
fi

# --- 10 CI wiring ---
nvars=$(gh variable list 2>/dev/null | wc -l)
if [ "$nvars" -ge 8 ]; then ok "10 repo variables ($nvars)"; else bad "10 repo variables" "expected 8, found $nvars — run setup_github.sh"; fi
if gcloud secrets describe github-pat --project="$PROJECT_ID" >/dev/null 2>&1; then
    prefix=$(gcloud secrets versions access latest --secret=github-pat --project="$PROJECT_ID" 2>/dev/null | cut -c1-11)
    case "$prefix" in
        github_pat_*) ok "10 PR credential (fine-grained PAT)";;
        gho_*)        ok "10 PR credential (gh CLI token fallback — see docs/GITHUB_APP_SETUP.md Step 1 for the durable option)";;
        *)            ok "10 PR credential (github-pat secret exists)";;
    esac
else
    bad "10 PR credential" "github-pat secret missing — run setup_github.sh"
fi
if gcloud secrets describe github-app-config --project="$PROJECT_ID" >/dev/null 2>&1; then
    ok "10 bot identity (GitHub App configured — issues post as the bot)"
else
    echo "[INFO] 10 bot identity not configured — issues attribute to the PAT owner (optional; docs/GITHUB_APP_SETUP.md)"
fi

# --- 11 gate green on main ---
# Judge the latest COMPLETED run — an in-progress run has no
# conclusion yet and must not read as failure.
gate=$(gh run list --workflow "Eval & Load Test Gate" --branch main --status completed --limit 1 --json conclusion --jq '.[0].conclusion' 2>/dev/null)
running=$(gh run list --workflow "Eval & Load Test Gate" --branch main --status in_progress --limit 1 --json databaseId --jq 'length' 2>/dev/null)
note=""; [ "${running:-0}" -ge 1 ] && note=" (a newer run is in progress)"
if [ "$gate" = "success" ]; then
    ok "11 Eval & Load Test Gate green on main${note}"
else
    bad "11 gate on main" "latest completed conclusion: ${gate:-none}${note}"
fi

# --- 12 branch protection ---
ctx=$(gh api "repos/{owner}/{repo}/branches/main/protection" --jq '.required_status_checks.contexts | join(",")' 2>/dev/null)
if echo "$ctx" | grep -q "Golden Eval" && echo "$ctx" | grep -q "Load Test"; then
    ok "12 branch protection (requires: $ctx)"
else
    bad "12 branch protection" "contexts: ${ctx:-none} — run setup_github.sh"
fi

echo ""
echo "=========================================="
echo "RESULT: ${PASS} passed, ${FAIL} failed"
echo "=========================================="
exit "$FAIL"
