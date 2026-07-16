# CI/CD and GitHub Integration

> **Status:** This integration is planned for a future phase. The current
> focus is on the [Skill Evolution pipeline](skill-evolution/ALGORITHM.md).
> The content below documents the reactive loop's CI/CD setup for
> reference.

## GitHub Integration (Quality Agent)

Quality Agent and Evolution Agent authenticate to GitHub using two
backends (tried in order):

1. **`gh` CLI** (primary) — uses `GH_TOKEN` env var. In Cloud Run,
   stored in Secret Manager (`github-pat`) and mounted via
   `--set-secrets="GH_TOKEN=github-pat:latest"`.
2. **PyGithub fallback** — uses a GitHub App (private key + config
   from Secret Manager secrets `github-app-key` and `github-app-config`).

### Setup (gh CLI path — recommended)

1. Create a fine-grained PAT with Issues + Pull Requests + Contents
   permissions scoped to your repository
2. Store it in Secret Manager:
   ```bash
   echo -n "$GITHUB_TOKEN" | gcloud secrets create github-pat \
     --data-file=- --project="$PROJECT_ID"
   ```
3. Cloud Run deploy scripts mount it automatically via `--set-secrets`

### Setup (GitHub App fallback)

Follow [`docs/GITHUB_APP_SETUP.md`](GITHUB_APP_SETUP.md) to:
1. Create a GitHub App with Issues, Pull requests, Contents permissions
2. Install it on your repository
3. Store the private key and config in Secret Manager

### Labels

Run the setup script to create issue labels:

```bash
export GITHUB_TOKEN="github_pat_..."   # one-time, for label creation only
./scripts/setup/setup_github.sh
```

This creates: `quality`, `routing`, `hallucination`, `prompt-gap`, `tool-error`.

## CI/CD Setup (GitHub Actions + GCP)

GitHub Actions authenticates to GCP via **Workload Identity Federation**
(WIF) -- no service account keys stored in GitHub. The setup scripts
handle everything.

### Step-by-step

**1. Prerequisites**

- A GCP project with billing enabled
- `gcloud` CLI authenticated as project owner/editor
- `gh` CLI authenticated (`gh auth login`)
- A GitHub repository (fork or clone this repo)

**2. Set up GCP infrastructure**

```bash
cp .env.example .env
# Edit .env: set PROJECT_ID to your GCP project
bash scripts/setup/setup_gcp.sh
```

This enables required APIs (Vertex AI, BigQuery, Cloud Run, etc.),
creates the BigQuery dataset, and grants IAM permissions.

**3. Set up GitHub <-> GCP connection**

```bash
bash scripts/setup/setup_github.sh
```

This script does 5 things:
1. Creates GitHub issue labels (quality, routing, hallucination, evolution, etc.)
2. Creates a **Workload Identity Federation** pool and OIDC provider
3. Creates a GCP service account (`github-actions-evolution@...`)
   and binds it to WIF so GitHub Actions can impersonate it
4. Sets GitHub repo variables via `gh variable set`
5. Stores GitHub PAT in Secret Manager as `github-pat`

**4. (Optional) Set up the GitHub App**

Only needed if you want the PyGithub fallback auth path.
Follow [`docs/GITHUB_APP_SETUP.md`](GITHUB_APP_SETUP.md).

**5. Create the test BigQuery dataset**

CI uses a separate dataset so test traffic doesn't pollute production:

```bash
source .env
bq mk --location="${DATASET_LOCATION:-us-central1}" \
  --dataset "${PROJECT_ID}:logging_test"
```

Set the test dataset in GitHub:
```bash
gh variable set TEST_DATASET_ID --body "logging_test" --repo YOUR_ORG/YOUR_REPO
```

### GitHub repo variables

After running `scripts/setup/setup_github.sh`, these variables are set on the repo:

| Variable | Example | Set by |
|----------|---------|--------|
| `PROJECT_ID` | `my-gcp-project` | `setup_github.sh` |
| `REGION` | `us-central1` | `setup_github.sh` |
| `WIF_PROVIDER` | `projects/123/locations/global/workloadIdentityPools/github-actions/providers/github-provider` | `setup_github.sh` |
| `WIF_SERVICE_ACCOUNT` | `github-actions-evolution@my-project.iam.gserviceaccount.com` | `setup_github.sh` |
| `DATASET_ID` | `agent_logs` | `setup_github.sh` |
| `TABLE_ID` | `agent_events` | `setup_github.sh` |
| `DATASET_LOCATION` | `us-central1` | `setup_github.sh` |
| `TEST_DATASET_ID` | `logging_test` | `setup_github.sh` |
| `SUPERVISOR_VERTEX_PROMPT_ID` | `123456789` | `setup_github.sh` (after `prompt_manager.py setup`) |
| `POLICY_VERTEX_PROMPT_ID` | `987654321` | `setup_github.sh` (after `prompt_manager.py setup`) |

### How WIF authentication works

```text
GitHub Actions runner
  | requests OIDC token from GitHub
GitHub OIDC provider
  | issues JWT with repo identity
GCP Workload Identity Federation
  | validates JWT, maps to service account
GCP Service Account (github-actions-evolution@...)
  | short-lived credentials
Vertex AI, BigQuery, Secret Manager
```

No service account keys are stored anywhere. The WIF pool is scoped
to your GitHub organization, and the service account binding is scoped
to your specific repository.

### Service account permissions

The `github-actions-evolution` service account handles eval, evolution,
and deployment:

| Role | Purpose |
|------|---------|
| `roles/aiplatform.user` | Call Gemini models via Vertex AI |
| `roles/bigquery.dataViewer` | Read agent analytics data |
| `roles/bigquery.jobUser` | Run BigQuery queries |
| `roles/secretmanager.secretAccessor` | Read GitHub PAT and App credentials |
| `roles/run.admin` | Deploy Cloud Run services and jobs |
| `roles/cloudbuild.builds.editor` | Build container images |
| `roles/storage.admin` | Access Cloud Build storage buckets |
| `roles/iam.securityAdmin` | Grant IAM bindings during deploy |
| `roles/cloudscheduler.admin` | Create/update Cloud Scheduler jobs |
| `roles/serviceusage.serviceUsageAdmin` | Enable GCP APIs |
| `roles/iam.serviceAccountUser` | Attach SAs to Cloud Run services |

### Verify the setup

Push a commit to main or open a PR. Two CI jobs should run:
- **Golden Eval** -- should pass in ~1 minute
- **Load Test** -- should pass in ~5-10 minutes

Check the Actions tab for results.

## CI Quality Gate

Every PR runs two jobs in parallel (`.github/workflows/eval.yml`):

**Job 1: Golden Eval** (`eval/tests/test_eval.py`) -- deterministic regression
tests against `eval/data/eval_cases.json`. Verifies routing, tool use, and
out-of-scope handling haven't regressed.

**Job 2: Load Test** (`eval/tests/test_load.py`) -- generates fresh synthetic
questions, runs them through the supervisor, and enforces operational
baselines defined in `eval/data/baselines.json`:

| Check | Metric | baselines.json key | Default |
|-------|--------|--------------------|---------|
| Quality gate | Meaningful response rate | `quality_threshold` | 0.8 (80%) |
| Error rate | Runtime error rate | `error_rate` | 0.15 (15%) |
| Latency budget | P95 latency | `p95_latency_ms` | 120000 (2 min) |
| All baselines | avg_latency, avg_turns, etc. | all keys in `budgets` | see baselines.json |

`eval/data/baselines.json` is the single source of truth. Env vars override
individual budgets for CI flexibility. Recalibrate from observed metrics:

```bash
python eval/scoring/check_budget.py eval/load_test_report.json                   # check against baselines
python eval/scoring/check_budget.py eval/load_test_report.json --record-baseline # recalibrate with headroom
```

**Deploy** (`.github/workflows/deploy.yml`) runs when a PR is merged
into main or triggered manually. It generates `.env` from `.env.example`,
overriding project-specific values (`PROJECT_ID`, `REGION`, `DATASET_ID`,
`TABLE_ID`, `DATASET_LOCATION`) with GitHub Actions variables. All other
config (model IDs, service names, load test params) uses `.env.example`
defaults.

**Fast Prompt Deploy** (`.github/workflows/deploy_prompts.yml`) --
*reactive loop only*. Runs when *only* `prompts.py` files change on push
to main. Calls `scripts/demo/reactive_loop/prompt_manager.py update` to push the new
prompt text to Vertex AI Prompt Manager (~30 seconds vs ~11 minutes for
a full rebuild). Skill evolution deploys via PR with the evolved
`SKILL.md` -- it does not use Prompt Manager.

## Vertex AI Prompt Manager (Reactive Loop only)

The reactive loop uses [Vertex AI Prompt Manager](https://cloud.google.com/vertex-ai/generative-ai/docs/prompt-gallery/prompt-manager)
for fast prompt updates without redeployment.

**Rationale:** In the reactive loop, fixes are incremental prompt tweaks
(add a routing rule, fix a hallucination pattern). Pushing these to
Vertex AI takes ~30 seconds vs redeploying the Cloud Run service
(~11 minutes). Agents read their prompt from Vertex AI at startup, so
the next request picks up the fix immediately.

Skill evolution does not use Prompt Manager. The entire `SKILL.md` is
evolved holistically and deployed via PR -- there are no incremental
prompt patches to push.

**How it works:**
- `scripts/demo/reactive_loop/prompt_manager.py setup` -- reads `prompts.py` files, creates
  prompts in Vertex AI, writes prompt IDs to `.env`
- `scripts/demo/reactive_loop/prompt_manager.py update` -- pushes local `prompts.py` text
  to Vertex AI (creates a new version)
- `scripts/demo/reactive_loop/prompt_manager.py show` -- displays current prompt text and
  version from Vertex AI
- At runtime, agents check for `SUPERVISOR_VERTEX_PROMPT_ID` /
  `POLICY_VERTEX_PROMPT_ID` env vars. If set, they load prompts from
  Vertex AI; if not, they fall back to local `prompts.py`

**Two deploy paths:**

```text
PR with code changes  -> eval.yml (tests) -> merge -> deploy.yml (full ~11min deploy)
PR with only prompts  -> eval.yml (tests) -> merge -> deploy_prompts.yml (~30sec API update)
```

**Setup** is integrated into existing scripts:
- `bash scripts/setup/setup_gcp.sh` creates prompts in Vertex AI (step 7)
- `bash scripts/setup/setup_github.sh` sets prompt IDs as GitHub repo variables (step 5)

**Manual usage:**
```bash
bash scripts/demo/reactive_loop/prompt_manager.sh setup    # create prompts, write IDs to .env
bash scripts/demo/reactive_loop/prompt_manager.sh update   # push local prompts to Vertex AI
bash scripts/demo/reactive_loop/prompt_manager.sh show     # display current Vertex AI prompts
```
