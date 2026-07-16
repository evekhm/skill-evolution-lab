# Skill Evolution Lab

A multi-agent system that **learns from its own execution traces** and
evolves structured skill documents -- deployed end-to-end on Google
Cloud, with the Skill Registry as the source of truth and every change
flowing through a pull request.

> **Read the story first:**
> [Your Agent Can Learn From Its Own Conversations](https://medium.com/@evekhm/your-agent-can-learn-from-its-own-conversations-26f7d46ac325)
> walks through the evolution algorithm on a single agent, and the SDK's
> [skill evolution lab](https://github.com/GoogleCloudPlatform/BigQuery-Agent-Analytics-SDK/tree/main/examples/skill_evolution_lab)
> is the minimal, runnable companion to that post. This repo is the
> production continuation: the same loop running against a deployed
> multi-agent stack, on a schedule, with CI gates and one-command
> rollback.

## What This System Does

This repo is a complete, deployed demonstration of an agent system that
improves itself from its own production traffic — with humans approving
every change.

**The product side** is an HR assistant: employees ask a supervisor
agent about PTO, sick leave, expenses, benefits, or "how many working
days until my leave starts", and the supervisor fans the question out
to specialist agents and synthesizes one answer. It runs on Vertex AI
Agent Engine and Cloud Run, with a chat UI available through Gemini
Enterprise.

**The learning side** is a closed loop around that assistant:

1. **Observe** — every conversation turn is logged to BigQuery,
   tagged with the skill version that produced it.
2. **Detect** — a daily quality agent scores recent sessions against
   curated Golden Q&A and files GitHub issues for failures.
3. **Learn** — a weekly evolution job reads the failing traces,
   dispatches a fleet of analyst agents to diagnose each failure,
   consolidates their patches into candidate `SKILL.md` documents, and
   keeps only the candidate that empirically scores best on replayed
   traffic.
4. **Propose** — the winning skills are published to the Skill
   Registry as new revisions and arrive as a pull request. CI
   hard-tests the evolved skill (routing, fan-out, quality budgets);
   candidates that gamed their training score die here.
5. **Activate** — a human merges the PR; the deploy workflow
   reconciles git with the Skill Registry and redeploys, and the
   agents fetch the new revision at startup. Rollback to the baseline
   is one command.

The demo ships with a deliberately flawed V0 skill (baked facts that
block the agent's own lookup tool, plus "accept the user's figure"
parroting on corrections) so you can watch the loop find and repair
real, reproducible defects end to end. Behavior lives in `SKILL.md`
documents — versioned, diffable, PR-reviewable — so "the agent
learned something" is always a concrete artifact a human signed off
on.

## What are Skills?

A **skill** is a structured markdown document (`SKILL.md`) that encodes
everything an agent needs to know about its domain: role, tool-use
instructions, topic expertise, scope boundaries, and response patterns.

```text
agents/enterprise/policy_agent/skill/
  SKILL.md              # The skill document (loaded as system instruction)
  references/           # Supporting data referenced by the skill
```

Skills turn agent behavior into a **learnable, versionable, reviewable**
artifact:

- **Human-readable** -- markdown a domain expert can read and edit
- **Version-controlled** -- diffs show exactly what the agent learned
- **PR-reviewable** -- domain experts approve changes before deployment
- **Evolved** -- the system writes skills from execution experience

At startup, each agent loads `SKILL.md` as its system instruction via
`skill_loader.py` -- from the **Skill Registry** (newest revision) when
`SKILL_SOURCE=registry`, with the packaged file as fallback. The skill
document is the single source of truth for agent behavior.

## How Skills Evolve

The system has one manual input: **Golden Q&A** -- curated
question-answer pairs that define what correct behavior looks like.
Everything else is automated.

### The single input

Golden Q&A (`eval/data/golden_evals.json`) feeds three consumers:
- **The user simulator** mirrors these facts to adversarially
  stress-test the agent
- **The LLM Judge** embedding-matches conversations to Golden Q&A to
  inject expected answers into the scoring prompt
- **The evolution engine** works on the T+/T- labels the judge produces

### Bootstrap: V0 to production-ready

1. Deploy the agent with a deliberately minimal skill (V0)
2. The user simulator generates adversarial traffic -- multi-turn
   conversations that push back on wrong answers using Golden Q&A facts
3. The LLM Judge scores each conversation against Golden Q&A ground
   truth and partitions into successes (T+) and failures (T-)
4. A parallel analyst fleet (~100 agents) examines trajectories and
   proposes skill patches
5. A patch consolidator merges patches into an evolved SKILL.md
6. Redeploy, re-generate traffic, re-score, repeat

Results: V0 (54%) -> V1 (97%) -> V2 (98%) on 205 multi-turn
conversations. Inspired by [Trace2Skill](https://arxiv.org/abs/2603.25158)
and [AutoSkill](https://arxiv.org/abs/2603.01145) -- see
[the paper analysis](docs/skill-evolution/RESEARCH.md).

### Production: monitoring and healing

Once deployed, two workflow agents maintain quality autonomously:
- **Quality Agent** (daily sentinel) scores production sessions
  against Golden Q&A, detects regressions via BigQuery history,
  creates GitHub issues
- **Skill Evolution Agent** (weekly healer) re-runs the evolution loop
  when enough failures accumulate, using real production traces

New topics that Golden Q&A doesn't cover surface as `new-topic` issues
for a human decision: add the capability or mark it out-of-scope.

See [Skill Evolution docs](docs/skill-evolution/) for the full lifecycle
narrative and algorithm details.

## Architecture

The system has two layers: **enterprise agents** that serve end users,
and **workflow agents** that test, monitor, and evolve the enterprise
agents. Three infrastructure pieces connect them: **BigQuery** holds
every execution trace, the **Skill Registry** holds every skill
revision, and **GitHub** holds the review gate between the two.

### Serving path (what runs where)

```text
  Gemini Enterprise chat UI              Traffic Generator
    (optional frontend)             (simulated users, multi-turn)
             |                                  |
             +----------------+-----------------+
                              v
             +--------------------------------+
             |      Knowledge Supervisor      |   Vertex AI Agent Engine
             |  fan-out + synthesis (root)    |
             |  SKILL.md from Skill Registry  |
             |  BigQuery Analytics plugin     |
             +-------+----------------+-------+
                     |   AgentTool    |
                     |   over A2A     |
            +--------v-------+  +-----v------------+
            |  Policy Agent  |  |  HR Calculator   |   Cloud Run
            |  SKILL.md +    |  |  (deterministic  |
            |  lookup tools  |  |   date/PTO math) |
            +--------+-------+  +------------------+
                     |
                     v
        +---------------------------+
        |       Skill Registry      |   Gemini Enterprise Agent Platform
        |  (append-only revisions)  |
        +---------------------------+
```

- The **supervisor** is the root agent on Vertex AI Agent Engine. It
  wraps each specialist as an `AgentTool`, so a compound question fans
  out to several specialists in one turn and the answers are
  synthesized into a single response.
- **Policy Agent** answers company-policy questions on Cloud Run behind
  an A2A endpoint, using tool-based lookups. Its `SKILL.md` is the main
  evolution target. A **Benefits Agent** skill is seeded in the registry
  and joins the topology when its service is deployed.
- **HR Calculator** computes PTO balances and working days with
  deterministic tools; it has no skill to evolve.
- Skill-bearing agents call the **Skill Registry** at startup
  (`GetSkill`, newest revision) and fall back to the packaged file on
  any failure. The startup log line
  `Loaded skill from registry <id> (revision <sha>)` is the live proof
  of which revision serves traffic.
- The supervisor's **BigQuery Agent Analytics plugin** logs every event
  to the `agent_events` table, tagged with the skill version from the
  SKILL.md frontmatter (`custom_tags.agent_version`).

### The evolution loop (end to end)

```text
 (1) traffic                     (2) traces
 users / simulator --> supervisor --> BigQuery agent_events
                                      (tagged agent_version)
                                              |
                               (3) Cloud Scheduler (weekly)
                                              v
                               +--------------------------+
                               |   skill-evolution-agent  |  Cloud Run Job
                               |   quality report from BQ |
                               |   -> gate: enough fails? |
                               |   -> bottleneck: which   |
                               |      agent is at fault?  |
                               |   -> analyst fleet       |
                               |   -> best-of-N candidates|
                               +------+-------------+-----+
                          (4a) push   |             |  (4b) open PR
                                      v             v
                            Skill Registry       GitHub PR
                            (new revision)          |
                                       (5) CI: Eval & Load Test Gate
                                           version-aware assertions
                                                    |
                                       (6) human reviews and merges
                                                    v
                                           deploy.yml (WIF auth)
                                           registry sync + redeploy
                                                    |
                                                    v
                                     (7) agents fetch merged revision
                                         --> back to (1), next window
```

1. **Traffic** -- real users (or the traffic generator's simulated
   users) talk to the deployed supervisor; specialists answer through
   it.
2. **Traces** -- every turn lands in BigQuery, version-tagged, so each
   evolution round analyzes only traffic from the currently deployed
   skill.
3. **Scheduled analysis** -- Cloud Scheduler fires the evolution job.
   It builds a quality report from the BigQuery window
   (`QUALITY_SOURCE=bigquery`), proceeds only past a failure-count
   gate, attributes failures to the responsible agent, runs the
   analyst fleet, and scores best-of-N candidate skills on the evolve
   set.
4. **Publish** -- winning skills are pushed to the Skill Registry as
   new revisions, and a pull request with the evolved `SKILL.md` opens
   on this repo (the job token-clones the repo inside its container).
5. **CI adjudicates** -- the Eval & Load Test Gate runs golden evals
   and a load test on the PR. The gate is version-aware: baseline V0
   skills are held to baseline expectations, while an evolved skill
   (version >= 1) must pass the full routing, fan-out, and quality
   assertions. A candidate that gamed its evolve-set score dies here,
   in the PR record, before it ever serves traffic.
6. **Merge activates** -- merging triggers `deploy.yml`: it re-seeds
   the registry from the merged `SKILL.md` (normally a SKIP because
   the job already pushed that exact revision -- the SKIP is the
   git-to-registry reconciliation proof), then redeploys the agents.
7. **The loop closes** -- restarted agents fetch the merged revision,
   the next traffic window measures the new version under its own
   `agent_version` tag, and the next scheduled run starts from clean
   data.

Rollback is one command
(`scripts/demo/skill_evolution/rollback_demo.sh`): V0 is republished as
the newest registry revision and the agents restart onto it, while the
evolved revisions stay in the append-only history.

### Where each piece runs

| Component | Runtime | Trigger |
|-----------|---------|---------|
| knowledge_supervisor | Vertex AI Agent Engine | user / API calls |
| policy_agent, hr_calculator | Cloud Run (A2A services) | supervisor fan-out |
| traffic_generator | local CLI or Cloud Run Job | manual / demo scripts |
| quality_agent | Cloud Run Job | Cloud Scheduler (daily) |
| skill_evolution_agent | Cloud Run Job | Cloud Scheduler (weekly), quality issues, or manual |
| Eval & Load Test Gate (`eval.yml`) | GitHub Actions | every PR and push to main |
| Deploy to GCP (`deploy.yml`) | GitHub Actions (WIF) | merge to main |

### Components in detail

**Enterprise agents** (`agents/enterprise/`) — serve end users:

- **knowledge_supervisor** — the root agent on Vertex AI Agent Engine.
  Receives every user question, fans out to specialists as `AgentTool`
  calls, and synthesizes one answer. Its thin `SKILL.md` holds routing
  conventions. The BigQuery Analytics plugin rides here, logging every
  event. Key files: `app/agent.py`, `app/skill/SKILL.md`.
- **policy_agent** — company-policy specialist on Cloud Run behind an
  A2A endpoint. Answers PTO, sick leave, remote work, expenses, and
  holiday questions with the `lookup_company_policy` tool over the
  policy corpus. Its `SKILL.md` is the primary evolution target — the
  V0 baseline deliberately blocks the tool (baked facts + defer-to-HR)
  and parrots corrections. Key files: `agent.py`, `tools.py`,
  `skill_loader.py`, `skill/SKILL.md`.
- **hr_calculator** — deterministic math specialist on Cloud Run:
  PTO balances, working days for date ranges, disability pay. Pure
  tools, no skill to evolve. Key file: `agent.py`.
- **benefits_agent** — benefits specialist defined by its skill
  (`skill/SKILL.md`). Runs in-process in the local topology and is
  seeded into the Skill Registry; joins the deployed topology when a
  service for it exists.

**Workflow agents** (`agents/workflow/`) — test, monitor, and evolve
the stack:

- **traffic_generator** — produces synthetic traffic: single-turn
  question sets, scripted multi-turn corrections (the user pushes back
  with a wrong figure), and a Golden-Q&A-aware adversarial user
  simulator. Targets the local supervisor or the deployed Agent Engine.
  Key files: `main.py`, `user_simulator.py`.
- **quality_agent** — the daily sentinel (Cloud Run Job + Scheduler).
  Pulls recent BigQuery sessions filtered by `agent_version`, scores
  them with the LLM judge against Golden Q&A, and files GitHub issues
  for failures. Key files: `main.py`, `tools.py`, `quality_report.py`.
- **skill_evolution_agent** — the weekly healer (Cloud Run Job +
  Scheduler). One run: quality report from BigQuery → failure-count
  gate → bottleneck attribution (which agent caused each failure) →
  agentic analysts investigate each failure with tool access → patch
  scoring and consolidation → best-of-N candidate skills scored on the
  evolve set → winners pushed to the Skill Registry → PR opened. Key
  files: `evolve.py` (core pipeline), `coevolve.py` (multi-agent
  orchestration), `bottleneck.py`, `agentic_analyst.py`,
  `patch_scoring.py`, `tools.py` (registry push + PR), `main.py` (CLI).

**Supporting pieces:**

- **`skill_loader.py`** — loads `SKILL.md` from the Skill Registry
  (newest revision) or the packaged file; exposes the frontmatter
  version that tags BigQuery events and drives the version-aware gate.
- **`eval/skill_evolution/registry_sync.py`** — Skill Registry CLI:
  `seed` (idempotent V0 publish), `push`, `revisions`, `verify-read`.
- **`eval/scoring/`** — `score_conversations.py` (SDK scorer: turn
  tagging, golden matching, quality report), `llm_judge.py` (the gate
  and load-test judge), `triage_report.py` (failure taxonomy + owner
  routing), `extract_ground_truth.py`.
- **`eval/tests/`** — the CI gate: `test_eval.py` (routing, compound
  fan-out, out-of-scope) and `test_load.py` (fresh-traffic quality,
  error rate, latency budgets), both version-aware via
  `skill_is_baseline()`.

## Bootstrap From Zero

Starting with an empty GCP project and an empty GitHub repo?
**[docs/BOOTSTRAP.md](docs/BOOTSTRAP.md)** is the complete tested path:
the few manual prerequisites (project, billing, PAT, auth), then every
remaining step scripted — GCP infrastructure, GitHub CI wiring, deploy,
and the e2e evolution loop — with a verification after each step.

## Run the Demo Locally

Run the full skill evolution pipeline on your machine. No GCP
deployment needed -- only Vertex AI API access for Gemini models.

### Prerequisites

- A Google Cloud project with Vertex AI API enabled
- `gcloud` CLI installed and authenticated:
  ```bash
  gcloud auth login
  gcloud auth application-default login
  ```
- `uv` installed ([Python package manager](https://docs.astral.sh/uv/))

### Step 1: Configure

```bash
cp .env.example .env
```

Edit `.env` and set `PROJECT_ID` to your GCP project ID. The rest of
the defaults work out of the box.

### Step 2: Set up environment

```bash
bash scripts/local/local_setup.sh
```

Syncs Python dependencies with `uv`, verifies GCP auth, and tests
that all agent modules import correctly.

### Step 3: Run the demo

```bash
# Quick run: 22 questions, ~15 minutes
bash scripts/demo/skill_evolution/run_demo.sh --quick

# Full run: 205 questions, ~1 hour
bash scripts/demo/skill_evolution/run_demo.sh --full
```

The demo script handles everything: restores the V0 baseline skill,
generates traffic, scores conversations, evolves the skill (V0 -> V1
-> V2), and produces a comparison report.

All artifacts are saved to `eval/runs/{timestamp}_demo_{mode}/`.

### What to expect

| Version | Meaningful Rate | What happened |
|---------|----------------|---------------|
| V0      | ~54-60%        | Baseline: minimal skill, agent redirects to HR for most questions |
| V1      | ~80-97%        | Evolution adds keyword mappings, anti-hallucination rules, scope boundaries |
| V2      | ~95-98%        | Refinement: edge cases, format improvements |

V0 -> V1 is the key jump. The evolved skill gains structured sections
(Tool Usage, Anti-Patterns, Out-of-Scope, Keyword Mappings) that the
V0 baseline lacks entirely.

Use `--reuse-v0` to skip V0 traffic generation on subsequent runs
(saves ~20 minutes on full runs):

```bash
bash scripts/demo/skill_evolution/run_demo.sh --full --reuse-v0
```

### Try it interactively

Start the agents locally and chat with the supervisor through the
ADK web UI:

```bash
bash scripts/local/local_start.sh
```

This launches:
- **policy_agent** on `http://localhost:8080` (A2A server)
- **hr_calculator** on `http://localhost:8081` (A2A server)
- **knowledge_supervisor** on `http://localhost:8000` (ADK web UI)

Open `http://localhost:8000` and ask questions like "What is our PTO
policy?" or "How many sick days do I get per year?"

Stop with `bash scripts/local/local_start.sh stop`.

### Manual step-by-step

For an interactive walkthrough of each pipeline stage, see:
- [Demo Script](docs/skill-evolution/DEMO_SCRIPT.md) -- step-by-step
  with `--step v0`, `--step v1`, `--step v2`
- [Quick Evolution Runbook](docs/skill-evolution/QUICK_EVOLUTION_RUNBOOK.md)
  -- manual commands for iteration and debugging

## Deploy to GCP

Full deployment to Cloud Run + Agent Engine. Takes ~25 minutes on
first deploy, faster on subsequent runs.

### Step 1: GCP infrastructure

```bash
source .env
gcloud config set project $PROJECT_ID
bash scripts/setup/setup_gcp.sh
```

Enables required GCP APIs (Vertex AI, Cloud Run, BigQuery, etc.),
creates the BigQuery dataset for Agent Analytics, seeds the Skill
Registry with the V0 skills, and grants IAM permissions.

### Step 2: Deploy

```bash
bash scripts/deploy/deploy_gcp.sh
```

Deploys all components in order:

| Step | Component | Time |
|------|-----------|------|
| 1 | policy_agent (Cloud Run) | ~3.5 min |
| 2 | hr_calculator (Cloud Run) | ~3 min |
| 3 | knowledge_supervisor (Agent Engine) | ~15 min |
| 4 | traffic_generator (Cloud Run Job) | ~2.5 min |
| 5 | quality_agent (Cloud Run Job + Scheduler) | ~3 min |
| 6 | skill_evolution_agent (Cloud Run Job + Scheduler) | ~3 min |
| | **Total** | **~30 min** |

You can also deploy individually:
```bash
(cd agents/enterprise/policy_agent && ./deploy.sh)
(cd agents/enterprise/hr_calculator && ./deploy.sh)
(cd agents/enterprise/knowledge_supervisor && ./deploy.sh)
```

> **First deploy note:** On a fresh project, the first Agent Engine
> deploy may fail with "failed to start and cannot serve traffic."
> This is a known race condition -- re-run `deploy_gcp.sh` and it
> will succeed.

### Step 3: Smoke test

```bash
bash scripts/test/smoke_test_deployed.sh
bash scripts/test/smoke_test_deployed.sh -q "How many PTO days do I have left?"

# Per-agent tests
bash agents/enterprise/policy_agent/send_query.sh -q "How many sick days do I get?"
bash agents/enterprise/hr_calculator/send_query.sh -q "How many PTO days do I have left?"
```

### Step 4: Connect Gemini Enterprise (optional)

Gemini Enterprise provides a chat UI that connects directly to the
deployed Agent Engine -- no custom frontend needed.

a. Go to [Gemini Enterprise](https://console.cloud.google.com/gemini-enterprise)
   in the GCP Console
b. Create a new **Gemini Enterprise app** (requires a Gemini Enterprise
   license -- a trial works)
c. Navigate to **Agents** > **Add Agent** > **Custom agent via Agent Engine**
d. Paste the Agent Engine ID from the deploy output:
   ```bash
   bash scripts/test/smoke_test_deployed.sh -q "test"  # prints the reasoning engine path
   ```
e. Open the app's web URL and select **HR Policy Assistant** from
   the agent picker

## Set Up the GitHub Repo

The production loop treats GitHub as part of the runtime: CI gates
every skill change, merges trigger deployment, and the evolution job
opens PRs with a bot credential. One script plus two manual steps wire
all of it.

### Step 1: Repo and prerequisites

- Fork or create the repo and clone it
- `cp .env.example .env` and set `PROJECT_ID`
- Authenticate the GitHub CLI: `gh auth login`

### Step 2: Run the setup script

```bash
# GH_PAT: a classic PAT with `repo` scope (or fine-grained with
# contents + pull-requests read/write on this repo). Without it the
# script falls back to your gh CLI token.
GH_PAT=<your PAT> bash scripts/setup/setup_github.sh
```

The script detects the repo from your git remote and configures, in
order:

| Step | What it does |
|------|--------------|
| Labels | Issue labels the quality agent uses (`quality`, `routing`, `hallucination`, `prompt-gap`, `tool-error`) |
| Workload Identity Federation | Creates the `github-actions` pool and OIDC provider in your GCP project, scoped to your GitHub org/user, so Actions authenticate to GCP with zero stored keys |
| CI service account | Creates `github-actions-fixer@<project>` with the roles the workflows need (Vertex AI, BigQuery, Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Scheduler, Logging), and binds it to this repo via WIF |
| Repo variables | Sets the Actions variables the workflows read: `PROJECT_ID`, `REGION`, `DATASET_ID`, `TABLE_ID`, `DATASET_LOCATION`, `TEST_DATASET_ID`, `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT` |
| Bot credential | Stores `GH_PAT` as the `github-pat` secret in Secret Manager -- the evolution job clones the repo and opens PRs with it (`deploy.sh` mounts it as `GH_TOKEN`) |
| Branch protection | main requires the Golden Eval + Load Test checks before merge |

The script is idempotent -- re-run it after changing `.env` or moving
projects. For a bot identity on issues and PRs (actions attributed to
an app instead of your user), additionally set up a GitHub App per
[`docs/GITHUB_APP_SETUP.md`](docs/GITHUB_APP_SETUP.md).

### Step 3: Verify

```bash
gh variable list          # 8 variables, PROJECT_ID = your project
gcloud secrets describe github-pat --project=$PROJECT_ID
gh api repos/{owner}/{repo}/branches/main/protection --jq '.required_status_checks.contexts'
```

Open any PR: the **Eval & Load Test Gate** should start automatically,
and after `scripts/setup/setup_gcp.sh` + a deploy, merging to main
triggers **Deploy to GCP**.

## Run the Production Loop Demo

The production loop is the deployed version of skill evolution
(see [the evolution loop](#the-evolution-loop-end-to-end) for the full
flow): real traffic lands in BigQuery, a scheduled job evolves the
skills, the result arrives as a pull request, and merging the PR
activates the new skill on the live agents. The Skill Registry is the
source of truth -- agents fetch the latest skill revision at startup,
and every change flows through git review before it reaches them.

Prerequisites: a deployed stack (previous section), `.env` sourced, and
`gh` authenticated against your fork.

### Step 1: Seed the V0 baseline

```bash
source .env
python eval/skill_evolution/registry_sync.py seed
python eval/skill_evolution/registry_sync.py revisions --agent policy_agent
```

Publishes each agent's `SKILL.md` to the Agent Platform Skill Registry
(`setup_gcp.sh` also runs this). The seed is idempotent: an unchanged
skill is skipped. The policy agent's V0 is deliberately flawed -- baked
policy facts plus "defer to HR for anything else" block the lookup tool
the agent already has, and "accept the user's figure" produces real
parroting on corrections. Those defects are the raw material the loop
will observe and repair.

At startup each agent logs its skill source, which is the proof the
registry is live:

```bash
gcloud logging read 'textPayload:"Loaded skill from registry"' \
  --project=$PROJECT_ID --freshness=1h --limit=4
```

### Step 2: Generate real traffic

```bash
# --concurrency 2 respects the default Agent Engine quota on fresh
# projects (90 requests/min; the generator also backs off on quota errors)
uv run python -m agents.workflow.traffic_generator.main \
  --from-file eval/data/questions/two_defect_evolve.json --concurrency 2
uv run python -m agents.workflow.traffic_generator.main \
  --from-file eval/data/questions/two_defect_corrections.json --multi-turn --concurrency 2
```

Drives questions through the deployed Agent Engine supervisor (omit
`--local` for the deployed path). Every turn is logged to the BigQuery
`agent_events` table by the Agent Analytics plugin, tagged with the
skill version from the frontmatter (`custom_tags.agent_version`). The
corrections file runs multi-turn: the user pushes back with a wrong
figure, which is how parroting becomes observable in the traces.

### Step 3: Run the evolution job

```bash
gcloud run jobs execute skill-evolution-agent --region $REGION --wait
```

The job also fires weekly from Cloud Scheduler (Mondays 09:00 UTC;
override the cadence at deploy time with
`EVOLUTION_SCHEDULE="*/30 * * * *"`). A full agent-decided run
(3 skills, best-of-5, 55-question validation per candidate) takes
~3 hours; for a demo-speed run (~1h) scope it to one agent:

```bash
gcloud run jobs execute skill-evolution-agent --region $REGION --wait \
  --args="--full-loop,--mode,policy_agent,--candidates,3,--quick"
```

Inside one run:

| Stage | What happens |
|-------|--------------|
| Pre-flight | Builds a quality report from real BigQuery traces (`QUALITY_SOURCE=bigquery`); falls back to generated traffic below `MIN_SESSIONS` |
| Gate | Proceeds only when there are enough failures to learn from |
| Bottleneck | Classifies each failure by source agent and picks which skill(s) to evolve |
| Evolution | Error analysts study the failures, propose patches, and best-of-N candidate skills are scored on the evolve set |
| Publish | The winning skills are pushed to the Skill Registry as new revisions |
| PR | A pull request with the evolved `SKILL.md` opens on the repo (token-cloned inside the job container) |

### Step 4: Review the PR

The PR body carries the baseline quality numbers; the diff is the
evolved skill itself. CI runs the Eval & Load Test Gate on it, and the
gate is version-aware: skills at version 0 are held to baseline
expectations, while an evolved skill (version >= 1) must pass the full
routing, fan-out, and quality assertions.

The gate has teeth. In one live run the evolved supervisor skill scored
80% on the evolve set by copying observed facts into its own summary
and answering directly -- which broke the routing contract, so the gate
refused it. A refused candidate stays in the registry history and in
the PR record; the next evolution round learns from a wider window.

### Step 5: Merge to activate

```bash
gh pr merge <PR_NUMBER> --merge

# 1. CI ran and is green
gh run list --workflow "Deploy to GCP" --limit 1
# 2. Registry sync reconciled the merged skill (SKIP = job already pushed it)
gh run view <run-id> --log | grep -E "SKIP|UPDATE|CREATE"
# 3. Agents serve the merged revision
gcloud logging read 'textPayload:"Loaded skill from registry"' \
  --project=$PROJECT_ID --freshness=15m --limit=4
# 4. A question V0 deflected now gets a grounded answer
bash scripts/test/smoke_test_deployed.sh
```

Merging triggers `deploy.yml`: it re-seeds the registry from the merged
`SKILL.md` (normally a SKIP, because the job already pushed that exact
revision -- the SKIP is the git-registry reconciliation proof), then
redeploys the agents, which fetch the merged revision at startup.

### Step 6: Roll back with one command

```bash
bash scripts/demo/skill_evolution/rollback_demo.sh
```

Resets the `SKILL.md` files to V0, republishes V0 to the Skill Registry
as the newest revision (the registry is append-only, so the evolved
revisions stay in history), restarts the policy agent and supervisor so
they serve V0 immediately, and prints the verification. Flags:
`--baseline stub|two-defect` (default `two-defect`) and
`--skip-redeploy` (agents pick up V0 on their next restart instead).

## Plug In Your Own Agent

The skill evolution pipeline is agent-agnostic. To evolve skills for
your own agent, you need three things: golden evals (expected Q&A
pairs), a V0 skill (baseline instructions), and a registry entry.

### Step 1: Create golden evals

Create a JSON file with curated question-answer pairs that define
your agent's expected behavior:

```json
{
  "eval_cases": [
    {
      "id": "pto_01",
      "question": "How many PTO days do I get per year?",
      "expected_answer": "You receive 20 PTO days per year, accrued monthly at approximately 1.67 days per month.",
      "topic": "pto"
    },
    {
      "id": "scope_salary",
      "question": "What is my salary?",
      "expected_answer": "I cannot provide salary information.",
      "topic": "out_of_scope"
    }
  ]
}
```

- Each entry needs `id`, `question`, `expected_answer`, and `topic`
- Use `"topic": "out_of_scope"` for questions the agent should decline
- See `eval/data/golden_evals.json` for a complete example

### Step 2: Create the V0 skill

Create a minimal skill document in your agent's skill directory.
This is the baseline that evolution will improve:

```text
your_agent/skill/
  SKILL.md       # Live version (overwritten during evolution)
  SKILL.v0.md    # Permanent backup (never modified)
```

Both files start with the same content:

```markdown
---
name: my-agent
description: |
  Brief description of what the agent does.
metadata:
  version: "0"
  author: human
  evolvable: true
---

# My Agent

You are a [role]. You have access to [tool_name].
Use it when you need to verify specific details.
Always base your answers on tool results, not assumptions.
```

Keep V0 deliberately minimal -- 3-5 sentences, no rules or edge
cases. Evolution adds those from execution experience.

### Step 3: Register the agent

Add your agent to `eval/skill_evolution/agent_registry.json`:

```json
{
  "agents": {
    "my_agent": {
      "skill_dir": "path/to/your_agent/skill",
      "label": "My Agent"
    }
  }
}
```

- `skill_dir`: relative path from repo root, must contain `SKILL.md`
- `label`: human-readable name for logs and reports

### Step 4: Extract ground truth

Generate the scoring context from your golden evals:

```bash
python eval/scoring/extract_ground_truth.py \
    --input path/to/your_golden_evals.json \
    --update-config eval/data/agent_context.json
```

This extracts factual ground truth and scope boundaries for the
LLM judge. Re-run whenever your golden evals change.

### Step 5: Run evolution

```bash
bash scripts/demo/skill_evolution/run_demo.sh --quick
```

Or run each step manually:

```bash
RUN_DIR="eval/runs/$(date +%Y-%m-%d_%H%M%S)_evolution"
mkdir -p "$RUN_DIR"

# Generate traffic against your agent
uv run python agents/workflow/traffic_generator/main.py \
    --local --local-agents --multi-turn \
    --from-file eval/data/questions/demo_quick.json \
    -o "$RUN_DIR/v0_traffic.json" --concurrency 10

# Score conversations
bash scripts/demo/skill_evolution/score.sh \
    -i "$RUN_DIR/v0_traffic.json" \
    -o "$RUN_DIR/v0_quality_report.json" --report

# Evolve via ADK agent (auto-selects candidates based on quality)
uv run python agents/workflow/skill_evolution_agent/main.py \
    --report "$RUN_DIR/v0_quality_report.json"

# Compare
python eval/scoring/score_conversations.py --compare \
    "$RUN_DIR/v0_quality_report.json:V0" \
    "$RUN_DIR/v1_quality_report.json:V1"
```

For full input schemas and pipeline details, see
[Inputs, Setup, and Pipeline](docs/skill-evolution/ALGORITHM.md#inputs-setup-and-pipeline)
in the algorithm reference.

## Quality Monitoring & Automated Evolution

After deployment, a closed-loop quality pipeline monitors agent
performance and evolves skills automatically from production data.
Two agents divide the work: a **daily sentinel** that monitors, and a
**weekly healer** that evolves.

### Quality Agent -- Daily Sentinel

Runs daily via Cloud Scheduler. Queries BigQuery for recent sessions
(filtered by `agent_version` from SKILL.md frontmatter), scores each
with an LLM judge against Golden Q&A ground truth, and creates GitHub
issues for failures.

```bash
# Deploy
bash agents/workflow/quality_agent/deploy.sh

# Run manually
gcloud run jobs execute quality-agent --project=$PROJECT_ID --region=$REGION

# Test locally (dry-run writes issues as .md files, no GitHub)
./agents/workflow/quality_agent/run_local.sh --dry-run --period 1d
```

The Quality Agent detects three types of production failures:

| Type | How detected | Action |
|------|-------------|--------|
| **Regression** -- questions that used to work now fail | CA Data Agent finds similar past sessions that were meaningful | `[URGENT]` label for immediate attention |
| **Persistent gap** -- known topics handled poorly | LLM Judge with Golden Q&A ground truth scores unhelpful/partial | Issues accumulate --> Skill Evolution Agent |
| **New topic** -- users asking about unanticipated things | CA Data Agent finds no historical sessions + no Golden Q&A match | `new-topic` --> human decision |

New-topic issues require a human decision: add the capability (create
Golden Q&A entries, add tool/data support, re-run evolution) or mark
out-of-scope (add to `agent_context.json` scope_decisions).

### Skill Evolution Agent -- Weekly Healer

Fires weekly from Cloud Scheduler, and each new quality issue also
triggers a threshold check via
`.github/workflows/skill_evolution_on_issue.yml`. When enough issues
have accumulated (default: 10), it queries BigQuery directly for
sessions tagged with the current `agent_version` -- always fresh data,
no intermediate downloads.

```bash
# Deploy
bash agents/workflow/skill_evolution_agent/deploy.sh

# Run batch evolution manually
gcloud run jobs execute skill-evolution-agent --project=$PROJECT_ID --region=$REGION

# Run locally
uv run python agents/workflow/skill_evolution_agent/main.py --batch
```

The pipeline: query BQ by version --> score with LLM judge -->
parallel analyst fleet --> consolidate patches --> evolved SKILL.md -->
registry revision + PR with before/after quality table.

### Version-Aware Filtering

Every BQ event carries the agent's skill version (read from SKILL.md
frontmatter). The quality agent filters sessions by version so it only
analyzes traffic from the currently deployed skill -- preventing
cross-version data contamination after an evolution.

### Why Separate Monitoring and Healing?

| | Quality Agent (sentinel) | Skill Evolution Agent (healer) |
|---|---|---|
| **Frequency** | Daily | Weekly (or threshold-triggered) |
| **Cost** | Low (LLM judge on ~50 sessions) | High (100 analysts + consolidation) |
| **Output** | GitHub issues (observation) | GitHub PR (action) |
| **Failure mode** | Missed problem (retry tomorrow) | Bad evolution (gate refuses, or revert PR) |

Configuration in `eval/data/quality_config.json`:
- `evolution.min_open_issues`: how many quality issues before batch
  evolution triggers (default: 10)

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full architecture.

## CI/CD and GitHub Integration

Two GitHub Actions workflows keep git, the Skill Registry, and the
deployed stack consistent:

- **Eval & Load Test Gate** (`.github/workflows/eval.yml`) -- runs on
  every PR and push to main. Golden eval tests check routing, tool use,
  and compound fan-out against a locally built supervisor; the load
  test generates fresh traffic and enforces quality, error-rate, and
  latency budgets from `eval/data/baselines.json`. The gate is
  version-aware: baseline V0 skills are held to baseline expectations,
  evolved skills (version >= 1) face the full assertions.
- **Deploy to GCP** (`.github/workflows/deploy.yml`) -- runs on merge
  to main, authenticated via Workload Identity Federation. Seeds the
  Skill Registry from the merged `SKILL.md` files (a SKIP means the
  registry already carries that exact revision), then rebuilds and
  redeploys all components.
- **Evolution on issue** (`.github/workflows/skill_evolution_on_issue.yml`)
  -- each new quality issue triggers a threshold check that can start
  a batch evolution run.

Setup guides: [`docs/CI_CD_GITHUB.md`](docs/CI_CD_GITHUB.md) (Workload
Identity Federation, repo variables, branch protection) and
[`docs/GITHUB_APP_SETUP.md`](docs/GITHUB_APP_SETUP.md) (the bot
identity used for issues and PRs).

## Project Structure

```text
agents/
  enterprise/                Enterprise agents -- serve end users
    policy_agent/            Cloud Run A2A sub-agent (company policies)
      skill/SKILL.md           Structured skill document (evolved by the loop)
      skill/SKILL.v0.md        Bare V0 baseline (local demo)
      skill/SKILL.v0_two_defect.md  Two-defect V0 (production loop demo)
      skill_loader.py          Loads SKILL.md (Skill Registry or file)
      tools.py                 lookup_company_policy, get_current_date
      deploy.sh                Deploy to Cloud Run
      send_query.sh            Smoke test the deployed service
    hr_calculator/           Cloud Run A2A sub-agent (dates, balances)
    knowledge_supervisor/    Agent Engine supervisor (fan-out + synthesis)
      app/agent.py             Supervisor with AgentTool-wrapped specialists
      app/skill/SKILL.md       Supervisor skill (routing conventions)
      deploy.sh                Deploy to Agent Engine
    benefits_agent/skill/    Benefits skill (in-process specialist)
  workflow/                  Workflow agents -- test and evolve the stack
    traffic_generator/       Generate + run synthetic multi-turn traffic
      main.py                  CLI: --local, --from-file, --multi-turn, ...
      user_simulator.py        Adversarial simulated user (Golden Q&A aware)
    quality_agent/           Quality monitoring (Cloud Run Job, daily)
      tools.py                 run_quality_report, create_github_issue
    skill_evolution_agent/   Skill evolution (Cloud Run Job, weekly)
      evolve.py                Core pipeline: analysts -> patches -> skill
      coevolve.py              Cross-agent co-evolution orchestrator
      bottleneck.py            Failure attribution across agents
      main.py                  CLI: --batch, --report, --full-loop, ...
      tools.py                 Full-loop tools + registry push + PR creation
.github/workflows/
  eval.yml                   Eval & Load Test Gate (version-aware)
  deploy.yml                 Registry sync + full redeploy on merge
  skill_evolution_on_issue.yml  Issue-triggered evolution threshold check
scripts/
  setup/setup_gcp.sh         One-time GCP setup (APIs, IAM, BQ, registry seed)
  setup/setup_github.sh      Labels + Workload Identity Federation for CI
  deploy/deploy_gcp.sh       Deploy all components to GCP
  local/local_setup.sh       Local dev environment (deps, auth, imports)
  local/local_start.sh       Start all agents locally
  demo/skill_evolution/
    run_demo.sh              Full local E2E pipeline (--full/--quick/--reuse-v0)
    rollback_demo.sh         One-command rollback to V0 (registry + redeploy)
    score.sh                 Score conversations with golden eval matching
  test/smoke_test_deployed.sh  End-to-end smoke test of the deployed stack
eval/
  data/
    golden_evals.json        Curated Q&A pairs (ground truth for scoring)
    agent_context.json       Scope decisions + extracted ground truth for judge
    baselines.json           Operational budgets for the load-test gate
    questions/               Question sets (demo, two-defect, corrections)
  scoring/
    score_conversations.py   SDK scorer: turn tagging, quality, golden matching
    llm_judge.py             LLM judge for the gate and load test
  tests/
    test_eval.py             Golden eval gate (routing, fan-out, out-of-scope)
    test_load.py             Load test gate (quality, error rate, latency)
  skill_evolution/
    registry_sync.py         Skill Registry CLI (seed / push / revisions)
    agent_registry.json      Maps agent names to skill directories
    reference_runs/          Reusable V0 baseline artifacts
  runs/                      Timestamped run outputs (gitignored)
docs/
  skill-evolution/           Algorithm, runbook, demo script, paper analysis
  CI_CD_GITHUB.md            CI/CD + Workload Identity Federation setup
  GITHUB_APP_SETUP.md        GitHub bot identity setup
  DESIGN.md                  Quality loop design
```

## Next Directions

- **Gate-aware candidate scoring** -- run the golden eval gate inside
  the evolution job so a candidate that would fail CI loses during
  best-of-N selection
- **Canary validation** -- traffic splitting between old and new agent
  versions before full rollout
- **Coverage tracker** -- cluster unanswered questions to discover
  topic gaps before users report them

See [`docs/DESIGN.md`](docs/DESIGN.md) for detailed design notes.

## Related Posts

- [Your Agent Can Learn From Its Own Conversations](https://medium.com/@evekhm/your-agent-can-learn-from-its-own-conversations-26f7d46ac325)
  -- the skill evolution algorithm, with the
  [runnable SDK lab](https://github.com/GoogleCloudPlatform/BigQuery-Agent-Analytics-SDK/tree/main/examples/skill_evolution_lab)
- [Your Agent Can Fix Its Own Prompt](https://medium.com/google-cloud/your-agent-can-fix-its-own-prompt-heres-how)
- [Your Agent Events Table Is Also a Test Suite](https://medium.com/google-cloud/your-agent-events-table-is-also-a-test-suite-999fbef885ed)
- [Your BigQuery Agent Analytics Table Is a Graph](https://medium.com/google-cloud/your-bigquery-agent-analytics-table-is-a-graph-heres-how-to-see-it-via-sdk-920b4ea14731)
- [BigQuery Conversational Analytics](https://cloud.google.com/bigquery/docs/conversational-analytics)
