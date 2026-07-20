# Bootstrap: from empty GCP project + empty repo to the working e2e demo

This is the complete, ordered path. Part A is the handful of steps that
can only be done by a human (accounts, billing, credentials). Everything
in Part B is a script this document tells you to run, in order, with a
verification after each step. When the last verification passes you have
the same environment as the reference deployment: the 3-agent stack
serving traffic, skills served from the Skill Registry, the scheduled
evolution loop, the CI gate, and merge-to-activate deploys.

Total time: ~60-90 minutes, most of it waiting on the first deploy.

---

## Part A — Manual prerequisites (one time, ~10 minutes)

### A1. Tools

You need: `gcloud`, `gh` (GitHub CLI), `uv`, `git`, `bq` and `gsutil`
(ship with gcloud). Verify:

```bash
gcloud version && gh --version && uv --version && bq version
```

### A2. GCP project

Create a fresh project and link billing (Console, or CLI):

```bash
gcloud projects create <YOUR_PROJECT_ID>
gcloud billing projects link <YOUR_PROJECT_ID> --billing-account=<BILLING_ACCOUNT_ID>
# find your billing account id: gcloud billing accounts list
```

Verify:

```bash
gcloud billing projects describe <YOUR_PROJECT_ID> --format="value(billingEnabled)"
# expect: True
```

### A3. GitHub repo

Create an empty repository (a LICENSE-only initialization is fine):

```bash
gh repo create <YOUR_GITHUB_USER>/<YOUR_REPO> --public --clone
# then copy this project's files into it, or clone your fork of it
```

### A4. Authentication

```bash
gcloud auth login
gcloud auth application-default login   # ADC — used by local scripts and the registry client
gcloud config set project <YOUR_PROJECT_ID>
gh auth login
```

### A5. PR credential (fine-grained PAT)

The evolution job opens PRs from its container using the `github-pat`
secret. Create a **fine-grained PAT** for it — one repo, two
permissions (Contents + Pull requests read/write), explicit expiry —
per [docs/GITHUB_APP_SETUP.md](GITHUB_APP_SETUP.md) Step 1, and export
it as `GH_PAT` before B3. (Skipping it falls back to your gh CLI
token: fine for a first spin, breaks when that login rotates.) The
same doc covers the optional GitHub App for bot-authored issues.

### A6. Configure `.env`

```bash
cd <YOUR_REPO>
export PROJECT_ID="<your-actual-project-id>"
sed -e "s/<YOUR_PROJECT_ID>/$PROJECT_ID/g" .env.example > .env
# generates .env with your project id substituted; the other defaults work.
```

---

## Part B — Scripted bootstrap (run in this order)

### B1. Local environment

```bash
bash scripts/local/local_setup.sh
```

What it does: `uv sync` (Python deps into `.venv`), verifies gcloud
auth, and smoke-imports every agent module.

Verify: the script ends with all checks green.

### B2. GCP infrastructure

```bash
bash scripts/setup/setup_gcp.sh
```

What it does: enables the GCP APIs (Vertex AI, Cloud Run, Cloud Build,
Artifact Registry, BigQuery, Logging, Storage), creates the BigQuery
dataset for Agent Analytics, the `cloud-run-source-deploy` Artifact
Registry repo, the GCS bucket for evolution run data, grants BigQuery/
logging/AI roles to the default compute service account, and seeds the
**Skill Registry** with each agent's V0 `SKILL.md`.

Verify (registry commands read `.env`, so source it first):

```bash
source .env
uv run python eval/skill_evolution/registry_sync.py revisions --agent policy_agent
# expect: revision 1 listed
```

### B3. GitHub wiring (CI + bot)

```bash
export GH_PAT=github_pat_...   # from A5
bash scripts/setup/setup_github.sh
```

What it does (idempotent, 7 steps): issue labels; **Workload Identity
Federation** (pool + OIDC provider scoped to your GitHub user/org) so
Actions authenticate to GCP with zero stored keys; the
`github-actions-fixer` CI service account with the roles the workflows
need; the 8 Actions **repo variables** the workflows read; the
`github-pat` **secret** in Secret Manager (the evolution job's PR
credential); **branch protection** on main requiring the Golden Eval +
Load Test checks.

Verify:

```bash
gh variable list      # 8 variables, PROJECT_ID matches your project
gcloud secrets describe github-pat --project=<YOUR_PROJECT_ID>
```

### B4. Push the code — first CI gate run

```bash
git add -A && git commit -m "Bootstrap: initial import" && git push origin main
```

Pushing to main triggers the **Eval & Load Test Gate** (`eval.yml`): it
builds the supervisor locally in CI (via WIF) and runs golden evals plus
a 20-question load test against Vertex AI in your project.

Verify:

```bash
gh run watch $(gh run list --workflow "Eval & Load Test Gate" --limit 1 --json databaseId --jq '.[0].databaseId')
# expect: both jobs green. V0 skills xfail the evolved-behavior tests by design.
```

> A fresh project has default Vertex quotas; a 429-heavy first run can
> happen. The gate retries quota errors automatically — rerun once with
> `gh run rerun <id>` if it still trips.

### B5. Deploy the stack

```bash
bash scripts/deploy/deploy_gcp.sh
```

Deploys, in order: policy_agent (Cloud Run), hr_calculator (Cloud Run),
knowledge_supervisor (Vertex AI Agent Engine), traffic_generator (Cloud
Run Job), quality_agent (Job + daily scheduler), skill_evolution_agent
(Job + weekly scheduler). Each component's `deploy.sh` grants its own
runtime IAM (including the Reasoning Engine service agent's
`aiplatform.user`, which is the Skill Registry read permission). ~30
minutes on first run.

> Known first-deploy race: the very first Agent Engine deploy can fail
> with "failed to start and cannot serve traffic". Re-run
> `deploy_gcp.sh` — the second pass succeeds.

Verify — agents must prove they serve skills from the registry. Run the
smoke test FIRST: the registry log line is emitted when a container
cold-starts on its first request, so it appears after traffic, and log
ingestion can lag a minute or two.

```bash
bash scripts/test/smoke_test_deployed.sh
gcloud logging read 'textPayload:"Loaded skill from registry"' \
  --project=<YOUR_PROJECT_ID> --freshness=30m --limit=4
# expect lines like:
#   Loaded skill from registry ks-policy-agent (revision <id>)
```

### B6. Run the e2e evolution loop

Follow **"Run the Production Loop Demo"** in the [README](../README.md):
seed traffic through the deployed supervisor, execute the evolution job,
review the PR it opens, merge to activate, roll back with one command.
Short version:

```bash
source .env
# --concurrency 2: fresh projects default to 90 Agent Engine
# requests/min (sessions + streams share the quota). The generator
# backs off on quota errors, but low concurrency keeps the run smooth.
uv run python -m agents.workflow.traffic_generator.main \
  --from-file eval/data/questions/two_defect_evolve.json --concurrency 2
uv run python -m agents.workflow.traffic_generator.main \
  --from-file eval/data/questions/two_defect_corrections.json --multi-turn --concurrency 2
gcloud run jobs execute skill-evolution-agent --region $REGION --wait
gh pr list   # the evolved-skill PR
```

Verify: a PR titled `Evolve ... skill` exists; the gate runs on it with
hard assertions (the skill carries version >= 1); the PR may also add
regression cases to `eval/data/eval_cases.json` + `golden_evals.json`
(failures the winning skill resolved — the gate grows each cycle);
merging it triggers `deploy.yml`, which reconciles the registry and
redeploys.

**Demo-speed variant (measured: 13m45s trigger-to-PR, vs ~1.5-3h full).** The full run lets
the job decide scope (often all three skills, best-of-5, 55-question
validation per candidate — thorough, and slow). For a live demo,
override the job args for one execution to evolve only the policy
agent with the quick scoring set:

```bash
gcloud run jobs execute skill-evolution-agent --region $REGION --wait \
  --args="--full-loop,--mode,policy_agent,--rounds,1,--candidates,3,--quick"
```

Same loop, same registry push, same PR — one agent and a lighter
validation set. Add `--trace-labels k=v` to evolve on one labeled
trace slice (generator runs auto-stamp `run_id` + `traffic_source`;
deploys stamp `sw_version`; the PR body records the selector). The scoping flags are **binding**: `--mode`,
`--rounds`, and `--candidates` are enforced at the tool layer (env
vars `EVOLUTION_TARGET_AGENTS`, `EVOLUTION_MAX_ROUNDS`,
`EVOLUTION_CANDIDATES`), so the orchestrating agent cannot widen the
run beyond what you asked for. One behavior to expect: when the
BigQuery window has too few sessions the job first generates its own
pre-flight traffic (~20 min extra).

---

## What you now have

| Piece | Where | Proof |
|-------|-------|-------|
| 3-agent stack | Agent Engine + Cloud Run | `smoke_test_deployed.sh` |
| Skills served from Skill Registry | Agent Platform | "Loaded skill from registry" log lines |
| Traces | BigQuery `agent_logs.agent_events` | rows tagged `agent_version` |
| Scheduled evolution | Cloud Run Job + Scheduler (Mon 09:00 UTC) | `gcloud scheduler jobs list` |
| Auto-PR with evolved skills | your repo | `gh pr list` after a job run |
| CI gate + merge-to-activate | GitHub Actions | green gate; deploy.yml on merge |
| One-command rollback | `scripts/demo/skill_evolution/rollback_demo.sh` | registry back on V0 |

## Troubleshooting

- **WIF provider NOT_FOUND right after creation** — propagation race;
  `setup_github.sh` retries automatically. If it exhausts retries, just
  re-run the script (idempotent).
- **Registry seed fails with 403** — check ADC (`gcloud auth
  application-default login`) and that `aiplatform.googleapis.com` is
  enabled (B2 does this).
- **Gate red with RESOURCE_EXHAUSTED** — Vertex quota on a fresh
  project; retry, or request a `gemini-2.5-flash` quota bump. Also
  avoid pushing (which triggers the gate) while a deploy, rollback, or
  evolution job is running — they share the project's model quota, and
  the overlap alone can fail the load test.
- **Traffic fails with "Quota exceeded ... Query Reasoning Engine
  requests"** — fresh projects allow 90 Agent Engine requests/min
  (session creation and streaming share it). The traffic generator
  backs off automatically; keep `--concurrency 2` for seeding, or
  request an increase on
  `QueryReasoningEngineRequestsPerMinutePerProjectPerRegion`.
- **Evolution job can't open a PR** — the `github-pat` secret is
  missing/expired, or the token lacks `repo` scope on this repo. Redo
  A5 + B3 step 6.
- **Evolution job killed at its task timeout** — a full co-evolution of
  all three skills (best-of-5 each) runs close to 3 hours; `deploy.sh`
  sets `--task-timeout=14400s` (4h) for headroom. If the bottleneck
  stage targets every agent and you need faster runs, lower the
  candidate count or seed a smaller traffic window.
