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

# setup_github.sh — Set up GitHub integration for the skill evolution loop.
#
# What this script does:
#   1. Installs Python deps (PyGithub, PyJWT, etc.)
#   2. Creates GitHub issue labels (quality, routing, hallucination, ...)
#   3. Sets up Workload Identity Federation so GitHub Actions can auth to GCP
#   4. Creates the CI service account GitHub Actions impersonates
#   5. Sets GitHub repo variables (PROJECT_ID, WIF_PROVIDER, etc.)
#   6. Stores the github-pat secret the evolution job uses to open PRs
#   7. Protects main (requires the Golden Eval + Load Test checks)
#   8. Optional: stores GitHub App secrets (bot identity, from GH_APP_* vars)
#
# Prerequisites:
#   - .env configured with PROJECT_ID
#   - `gh` CLI authenticated (gh auth login)
#   - GH_PAT env var with a repo-scoped PAT (step 6; falls back to the
#     gh CLI token, and skips with instructions when neither is available)
#   - Optional: GitHub App for a bot identity (see docs/GITHUB_APP_SETUP.md)
#
# Usage: bash scripts/setup/setup_github.sh
#        GH_PAT=ghp_xxx bash scripts/setup/setup_github.sh   # unattended

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/setup_github_$(date +%Y%m%d_%H%M%S).log"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================================="
echo "    GitHub Integration Setup"
echo "    Log: ${LOG_FILE}"
echo "=========================================================="

# --- Load .env ---
if [ -f "$PROJECT_ROOT/.env" ]; then
    source "$PROJECT_ROOT/.env"
else
    echo "ERROR: .env file not found at $PROJECT_ROOT/.env"
    exit 1
fi

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "your-project-id" ] || [ "$PROJECT_ID" = "<YOUR_PROJECT_ID>" ]; then
    echo "ERROR: PROJECT_ID not set. Please edit .env."
    exit 1
fi

# Detect repo from git remote
GITHUB_REPO=${GITHUB_REPO:-$(git remote get-url origin 2>/dev/null | sed 's|.*github.com[:/]\(.*\)\.git|\1|' || echo "")}
if [ -z "$GITHUB_REPO" ]; then
    echo "ERROR: Could not detect GitHub repo. Set GITHUB_REPO in .env."
    exit 1
fi

GITHUB_OWNER="${GITHUB_REPO%%/*}"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

echo "Project ID:    $PROJECT_ID"
echo "Project #:     $PROJECT_NUMBER"
echo "GitHub Repo:   $GITHUB_REPO"
echo "GitHub Owner:  $GITHUB_OWNER"
echo "----------------------------------------------------------"

# =========================================================================
# Step 1: Install Python dependencies
# =========================================================================
echo ""
echo "[1/8] Installing Python dependencies..."
if command -v uv &>/dev/null; then
    uv pip install PyGithub PyJWT cryptography google-cloud-secret-manager --quiet
else
    pip install PyGithub PyJWT cryptography google-cloud-secret-manager --quiet
fi
echo "  Done."

# =========================================================================
# Step 2: Create GitHub issue labels
# =========================================================================
echo ""
echo "[2/8] Creating GitHub issue labels..."

create_label() {
    local name="$1" color="$2" description="$3"
    if gh label create "$name" --color "$color" --description "$description" --repo "$GITHUB_REPO" 2>/dev/null; then
        echo "  Created label: $name"
    else
        echo "  Label '$name' already exists (skipped)"
    fi
}

if command -v gh &>/dev/null; then
    create_label "quality"       "d93f0b" "Auto-detected quality issue"
    create_label "routing"       "e99695" "Agent routing failure"
    create_label "hallucination" "f9d0c4" "Hallucinated response"
    create_label "prompt-gap"    "c5def5" "Missing prompt coverage"
    create_label "tool-error"    "bfdadc" "Tool execution failure"
else
    echo "  WARNING: 'gh' CLI not found. Install it: https://cli.github.com/"
    echo "  Or create labels manually on GitHub."
fi

# =========================================================================
# Step 3: Set up Workload Identity Federation for GitHub Actions
# =========================================================================
echo ""
echo "[3/8] Setting up Workload Identity Federation..."

WIF_POOL="github-actions"
WIF_PROVIDER="github-provider"

# Enable the APIs this script depends on (WIF + secret storage)
gcloud services enable iamcredentials.googleapis.com \
    secretmanager.googleapis.com \
    --project="$PROJECT_ID" --quiet

# Create WIF pool (idempotent)
if gcloud iam workload-identity-pools describe "$WIF_POOL" \
    --project="$PROJECT_ID" --location=global >/dev/null 2>&1; then
    echo "  WIF pool '$WIF_POOL' already exists."
else
    echo "  Creating WIF pool '$WIF_POOL'..."
    gcloud iam workload-identity-pools create "$WIF_POOL" \
        --project="$PROJECT_ID" \
        --location=global \
        --display-name="GitHub Actions" \
        --description="WIF pool for GitHub Actions CI/CD"
fi

# Create OIDC provider (idempotent)
if gcloud iam workload-identity-pools providers describe "$WIF_PROVIDER" \
    --project="$PROJECT_ID" --location=global \
    --workload-identity-pool="$WIF_POOL" >/dev/null 2>&1; then
    echo "  WIF provider '$WIF_PROVIDER' already exists."
else
    echo "  Creating WIF provider '$WIF_PROVIDER'..."
    gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" \
        --project="$PROJECT_ID" \
        --location=global \
        --workload-identity-pool="$WIF_POOL" \
        --display-name="GitHub" \
        --issuer-uri="https://token.actions.githubusercontent.com" \
        --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
        --attribute-condition="assertion.repository_owner == '${GITHUB_OWNER}'"
fi

# Get the full WIF provider resource name. Freshly created providers can
# take a few seconds to become readable — retry instead of dying on the
# propagation race.
WIF_PROVIDER_FULL=""
for attempt in 1 2 3 4 5; do
    WIF_PROVIDER_FULL=$(gcloud iam workload-identity-pools providers describe "$WIF_PROVIDER" \
        --project="$PROJECT_ID" --location=global \
        --workload-identity-pool="$WIF_POOL" \
        --format="value(name)" 2>/dev/null) && [ -n "$WIF_PROVIDER_FULL" ] && break
    echo "  Provider not readable yet (attempt ${attempt}/5); retrying in 10s..."
    sleep 10
done
if [ -z "$WIF_PROVIDER_FULL" ]; then
    echo "ERROR: WIF provider '$WIF_PROVIDER' still not readable after retries."
    exit 1
fi
echo "  WIF Provider: $WIF_PROVIDER_FULL"

# =========================================================================
# Step 4: Create & configure service account for GitHub Actions
# =========================================================================
echo ""
echo "[4/8] Configuring service account for GitHub Actions..."

GH_SA_NAME="github-actions-fixer"
GH_SA_EMAIL="${GH_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Create SA (idempotent)
if gcloud iam service-accounts describe "$GH_SA_EMAIL" \
    --project="$PROJECT_ID" >/dev/null 2>&1; then
    echo "  Service account '$GH_SA_EMAIL' already exists."
else
    echo "  Creating service account '$GH_SA_NAME'..."
    gcloud iam service-accounts create "$GH_SA_NAME" \
        --project="$PROJECT_ID" \
        --display-name="GitHub Actions CI/CD" \
        --description="Used by GitHub Actions for eval, remediation, and deploy"
fi

# Grant roles to the SA:
#   - Eval & remediation: Vertex AI, BigQuery, Secret Manager
#   - Deploy: Cloud Run, Cloud Build, IAM, Scheduler, Storage, Service Usage
echo "  Granting roles..."
# NOTE: no roles/iam.securityAdmin here — it carries setIamPolicy, which
# makes the CI identity owner-equivalent (it could grant itself any role),
# and it is impersonable from any branch of the repo via WIF (review #54
# finding 4). Project IAM bindings are created ONCE by setup_gcp.sh and
# the first operator-run deploy; the deploy scripts' re-grant calls
# tolerate permission denial in CI (the bindings already exist).
for role in \
    "roles/secretmanager.secretAccessor" \
    "roles/aiplatform.user" \
    "roles/bigquery.dataViewer" \
    "roles/bigquery.jobUser" \
    "roles/run.admin" \
    "roles/cloudbuild.builds.editor" \
    "roles/artifactregistry.writer" \
    "roles/logging.viewer" \
    "roles/storage.admin" \
    "roles/cloudscheduler.admin" \
    "roles/serviceusage.serviceUsageAdmin" \
    "roles/iam.serviceAccountUser"; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${GH_SA_EMAIL}" \
        --role="$role" \
        --quiet --no-user-output-enabled
    echo "    $role"
done

# Allow GitHub Actions to impersonate this SA
echo "  Binding WIF to service account..."
WIF_POOL_NAME="${WIF_PROVIDER_FULL%/providers/*}"
gcloud iam service-accounts add-iam-policy-binding "$GH_SA_EMAIL" \
    --project="$PROJECT_ID" \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/${WIF_POOL_NAME}/attribute.repository/${GITHUB_REPO}" \
    --quiet
echo "  Done."

# =========================================================================
# Step 5: Set GitHub repo variables
# =========================================================================
echo ""
echo "[5/8] Setting GitHub repo variables..."

if command -v gh &>/dev/null; then
    gh variable set PROJECT_ID          --body "$PROJECT_ID"              --repo "$GITHUB_REPO" && echo "  PROJECT_ID=$PROJECT_ID"
    gh variable set REGION              --body "${REGION:-us-central1}"   --repo "$GITHUB_REPO" && echo "  REGION=${REGION:-us-central1}"
    gh variable set DATASET_ID          --body "$DATASET_ID"             --repo "$GITHUB_REPO" && echo "  DATASET_ID=$DATASET_ID"
    gh variable set TABLE_ID            --body "$TABLE_ID"               --repo "$GITHUB_REPO" && echo "  TABLE_ID=$TABLE_ID"
    gh variable set DATASET_LOCATION    --body "$DATASET_LOCATION"       --repo "$GITHUB_REPO" && echo "  DATASET_LOCATION=$DATASET_LOCATION"
    gh variable set WIF_PROVIDER        --body "$WIF_PROVIDER_FULL"      --repo "$GITHUB_REPO" && echo "  WIF_PROVIDER=$WIF_PROVIDER_FULL"
    gh variable set WIF_SERVICE_ACCOUNT --body "$GH_SA_EMAIL"            --repo "$GITHUB_REPO" && echo "  WIF_SERVICE_ACCOUNT=$GH_SA_EMAIL"
    gh variable set TEST_DATASET_ID     --body "${TEST_DATASET_ID:-logging_test}" --repo "$GITHUB_REPO" && echo "  TEST_DATASET_ID=${TEST_DATASET_ID:-logging_test}"
else
    echo "  WARNING: 'gh' CLI not found. Set these variables manually:"
    echo "    GitHub > Settings > Secrets and variables > Actions > Variables"
    echo ""
    echo "    PROJECT_ID=$PROJECT_ID"
    echo "    REGION=${REGION:-us-central1}"
    echo "    DATASET_ID=$DATASET_ID"
    echo "    TABLE_ID=$TABLE_ID"
    echo "    DATASET_LOCATION=$DATASET_LOCATION"
    echo "    WIF_PROVIDER=$WIF_PROVIDER_FULL"
    echo "    WIF_SERVICE_ACCOUNT=$GH_SA_EMAIL"
    echo "    TEST_DATASET_ID=${TEST_DATASET_ID:-logging_test}"
fi

# =========================================================================
# Step 6: Store the github-pat secret (evolution job's PR credential)
# =========================================================================
# The evolution job runs in a container without a git identity; it clones
# the repo and opens PRs with GH_TOKEN read from this secret
# (skill_evolution_agent/deploy.sh mounts github-pat:latest).
echo ""
echo "[6/8] Storing github-pat secret in Secret Manager..."

if gcloud secrets describe github-pat --project="$PROJECT_ID" >/dev/null 2>&1; then
    echo "  Secret 'github-pat' already exists (skipped)."
else
    PAT_VALUE="${GH_PAT:-}"
    PAT_SOURCE="GH_PAT env var"
    if [ -z "$PAT_VALUE" ] && [ "${ALLOW_GH_TOKEN_FALLBACK:-}" = "1" ] \
        && command -v gh &>/dev/null; then
        # OPT-IN fallback (ALLOW_GH_TOKEN_FALLBACK=1): the gh CLI's own
        # OAuth token. It carries repo+workflow scope across EVERY repo
        # the operator can reach and would be mounted into LLM-driven
        # Cloud Run jobs — far broader than the single-repo fine-grained
        # PAT the docs recommend (review #54 finding 5). Never stored
        # silently: set GH_PAT, or opt in explicitly.
        PAT_VALUE=$(gh auth token 2>/dev/null || true)
        PAT_SOURCE="gh auth token (ALLOW_GH_TOKEN_FALLBACK=1 -- consider a dedicated repo-scoped PAT)"
    fi
    if [ -n "$PAT_VALUE" ]; then
        printf '%s' "$PAT_VALUE" | gcloud secrets create github-pat \
            --project="$PROJECT_ID" --data-file=-
        echo "  Created secret 'github-pat' from: $PAT_SOURCE"
    else
        echo "  WARNING: no GH_PAT env var set (and the gh-token fallback is"
        echo "  opt-in via ALLOW_GH_TOKEN_FALLBACK=1 — a dedicated repo-scoped"
        echo "  fine-grained PAT is the safe choice; see docs/GITHUB_APP_SETUP.md)."
        echo "  Create the secret manually before deploying the evolution job:"
        echo "    printf '%s' \"<YOUR_PAT>\" | gcloud secrets create github-pat \\"
        echo "      --project=$PROJECT_ID --data-file=-"
    fi
fi

# =========================================================================
# Step 7: Protect main (require the eval gate checks)
# =========================================================================
echo ""
echo "[7/8] Setting branch protection on main..."

if gh api -X PUT "repos/${GITHUB_REPO}/branches/main/protection" --input - >/dev/null <<'PROTECTION'
{
  "required_status_checks": {
    "strict": false,
    "contexts": ["Golden Eval", "Load Test"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
PROTECTION
then
    echo "  main requires: Golden Eval + Load Test."
else
    echo "  WARNING: could not set branch protection (plan/permissions?)."
    echo "  Set it manually: GitHub > Settings > Branches > main."
fi

# =========================================================================
# Done
# =========================================================================
echo ""
# =========================================================================
# Step 8: Bot identity (GitHub App) — optional
# =========================================================================
echo ""
echo "[8/8] Bot identity (GitHub App secrets)..."
if [ -n "${GH_APP_ID:-}" ] && [ -n "${GH_APP_INSTALLATION_ID:-}" ] && [ -n "${GH_APP_KEY_FILE:-}" ]; then
    if gcloud secrets describe github-app-key --project="$PROJECT_ID" >/dev/null 2>&1; then
        # Secret already stored — the local .pem may legitimately be
        # deleted by now; never demand it again.
        echo "  Secret 'github-app-key' already exists (skipped)."
    elif [ ! -f "${GH_APP_KEY_FILE}" ]; then
        echo "  ERROR: GH_APP_KEY_FILE not found: ${GH_APP_KEY_FILE}"
        echo "  If you already deleted the .pem: app settings -> Private keys"
        echo "  -> Generate a private key, then re-run with the new path."
        exit 1
    else
        gcloud secrets create github-app-key --project="$PROJECT_ID" \
            --data-file="${GH_APP_KEY_FILE}"
        echo "  Created secret 'github-app-key'."
    fi
    if gcloud secrets describe github-app-config --project="$PROJECT_ID" >/dev/null 2>&1; then
        echo "  Secret 'github-app-config' already exists (skipped)."
    else
        printf '{"app_id": %s, "installation_id": %s, "repo": "%s"}' \
            "${GH_APP_ID}" "${GH_APP_INSTALLATION_ID}" "${GITHUB_REPO}" \
            | gcloud secrets create github-app-config --project="$PROJECT_ID" --data-file=-
        echo "  Created secret 'github-app-config' (repo: ${GITHUB_REPO})."
    fi
    echo "  Quality-agent issues will post as the app bot after its next deploy."
else
    echo "  GH_APP_ID / GH_APP_INSTALLATION_ID / GH_APP_KEY_FILE not set — skipped."
    echo "  (Issues attribute to the PAT owner. See README 0.C.1 to create"
    echo "   the GitHub App, then re-run this script with the three vars.)"
fi

echo "=========================================================="
echo "GitHub Integration Setup Complete!"
echo ""
echo "Full log: ${LOG_FILE}"
echo ""
echo "What was configured:"
echo "  [1] Python deps (PyGithub, PyJWT, etc.)"
echo "  [2] GitHub labels (quality, routing, hallucination, ...)"
echo "  [3] Workload Identity Federation (GitHub Actions → GCP)"
echo "  [4] Service account: $GH_SA_EMAIL"
echo "  [5] GitHub repo variables (PROJECT_ID, WIF_PROVIDER, ...)"
echo "  [6] Secret Manager secret: github-pat (evolution job PR credential)"
echo "  [7] Branch protection on main (Golden Eval + Load Test required)"
if gcloud secrets describe github-app-config --project="$PROJECT_ID" >/dev/null 2>&1; then
    echo "  [8] Bot identity: CONFIGURED — quality issues post as the app bot"
else
    echo "  [8] Bot identity: not configured — issues attribute to the PAT owner"
    echo "      (optional; see docs/GITHUB_APP_SETUP.md Steps 2-4, then re-run)"
fi
echo "=========================================================="
