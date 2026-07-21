<!-- TOC -->
* [Skill Evolution Lab](#skill-evolution-lab)
  * [What This System Does](#what-this-system-does)
  * [Prerequisites](#prerequisites)
    * [1 — First time only: create the project and the repo](#1--first-time-only-create-the-project-and-the-repo)
    * [2 — Local machine: tools, auth, environment](#2--local-machine-tools-auth-environment)
      * [Tools and auth](#tools-and-auth)
      * [Configure `.env`](#configure-env)
      * [Python environment](#python-environment)
    * [3 — GCP: deploy the stack](#3--gcp-deploy-the-stack)
      * [3.1 — GCP infrastructure](#31--gcp-infrastructure)
      * [3.2 — Deploy all six components](#32--deploy-all-six-components)
      * [3.3 — Smoke test](#33--smoke-test)
      * [3.4 — Connect Gemini Enterprise (optional)](#34--connect-gemini-enterprise-optional)
    * [4 — GitHub: CI + bot wiring](#4--github-ci--bot-wiring)
    * [5 — Verify everything: one command](#5--verify-everything-one-command)
  * [Run the Demo](#run-the-demo)
    * [The one-command run](#the-one-command-run)
      * [Local](#local)
      * [Deployed](#deployed)
    * [The step-by-step walkthrough](#the-step-by-step-walkthrough)
    * [Step 1 — The starting point (defined, verifiable)](#step-1--the-starting-point-defined-verifiable)
    * [Step 2 — Generate labeled traffic (the system observes failures)](#step-2--generate-labeled-traffic-the-system-observes-failures)
    * [Step 3 — Run the evolution job (learn + propose)](#step-3--run-the-evolution-job-learn--propose)
    * [Step 4 — Review the PR (learning as an artifact)](#step-4--review-the-pr-learning-as-an-artifact)
    * [Choosing which traces to evolve on (labels)](#choosing-which-traces-to-evolve-on-labels)
    * [Step 5 — Merge to activate](#step-5--merge-to-activate)
    * [Step 6 — Verify the fix (the payoff)](#step-6--verify-the-fix-the-payoff)
    * [Step 7 — Roll back (back to the Step 1 state)](#step-7--roll-back-back-to-the-step-1-state)
  * [Alternative: Local-Only Demo (no deployment)](#alternative-local-only-demo-no-deployment)
    * [What to expect](#what-to-expect)
    * [Try it interactively](#try-it-interactively)
    * [Manual step-by-step](#manual-step-by-step)
  * [Architecture](#architecture)
    * [Serving path (what runs where)](#serving-path-what-runs-where)
    * [How a question flows (Agent Engine, AgentTool, A2A)](#how-a-question-flows-agent-engine-agenttool-a2a)
    * [The evolution loop (end to end)](#the-evolution-loop-end-to-end)
    * [Where each piece runs](#where-each-piece-runs)
    * [Components in detail](#components-in-detail)
    * [The full cycle, actor by actor](#the-full-cycle-actor-by-actor)
    * [The one manual input: Golden Q&A](#the-one-manual-input-golden-qa)
  * [Demo Variants — What Runs, What Is Cut, and Why](#demo-variants--what-runs-what-is-cut-and-why)
    * [The four ways to run it](#the-four-ways-to-run-it)
    * [Every step of the GCP demo run](#every-step-of-the-gcp-demo-run)
    * [What `--quick` cuts — and what it never touches](#what---quick-cuts--and-what-it-never-touches)
  * [Quality Monitoring & Automated Evolution](#quality-monitoring--automated-evolution)
    * [Quality Agent -- Daily Sentinel](#quality-agent----daily-sentinel)
    * [Skill Evolution Agent -- Weekly Healer](#skill-evolution-agent----weekly-healer)
    * [Version-Aware Filtering](#version-aware-filtering)
    * [Why Separate Monitoring and Healing?](#why-separate-monitoring-and-healing)
  * [Plug In Your Own Agent](#plug-in-your-own-agent)
    * [Step 1: Create golden evals](#step-1-create-golden-evals)
    * [Step 2: Create the V0 skill](#step-2-create-the-v0-skill)
    * [Step 3: Register the agent](#step-3-register-the-agent)
    * [Step 4: Extract ground truth](#step-4-extract-ground-truth)
    * [Step 5: Run evolution](#step-5-run-evolution)
  * [CI/CD and GitHub Integration](#cicd-and-github-integration)
  * [Project Structure](#project-structure)
  * [Backlog](#backlog)
  * [Next Directions](#next-directions)
  * [Related Posts](#related-posts)
<!-- TOC -->
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

**The product side — enterprise agents** (`agents/enterprise/`, they
serve end users):

- **`knowledge_supervisor`** — the root agent, deployed on **Vertex AI
  Agent Engine**. It owns the conversation: receives every employee
  question, decides which specialists are needed, calls them (several
  in one turn for compound questions), and synthesizes one answer.
- **`policy_agent`** — the company-policy specialist, deployed on
  **Cloud Run** behind an **A2A** endpoint. Answers PTO, sick leave,
  remote work, expense, and holiday questions using the
  `lookup_company_policy` tool. Its `SKILL.md` is the main evolution
  target.
- **`hr_calculator`** — the math specialist, also on **Cloud Run**
  behind A2A: PTO balances, working days between dates, disability
  pay. Deterministic tools, no skill to evolve.
- **`benefits_agent`** — the benefits specialist. It exists as a skill
  document (`agents/enterprise/benefits_agent/skill/`) with a Skill
  Registry entry and it evolves like the others; it runs **in-process**
  in the local topology, and the reference deployment has no Cloud Run
  service for it yet (the supervisor wires it in automatically once one
  is deployed — tracked in the backlog).

Employees reach the supervisor through a Gemini Enterprise chat UI (or
any API client); the specialists are implementation details they never
see.

**The operations side — workflow agents** (`agents/workflow/`, they
test, monitor, and evolve the enterprise agents; users never talk to
them):

- **`traffic_generator`** — produces synthetic traffic: question sets,
  scripted correction pushback, and a golden-aware adversarial user
  simulator. Local CLI or Cloud Run Job.
- **`quality_agent`** — the daily sentinel (Cloud Run Job, 08:00 UTC
  scheduler): judges recent sessions from BigQuery and files labeled
  GitHub issues for failures.
- **`skill_evolution_agent`** — the healer (Cloud Run Job; on demand,
  issue-threshold, or scheduled tick): runs the learn-propose pipeline
  described below and opens the PR.

**The learning side** is a closed loop around that assistant:

1. **Observe** — every conversation turn is logged to BigQuery,
   tagged with the skill version that produced it.
2. **Detect** — **`quality_agent`** (`agents/workflow/quality_agent/`,
   the Cloud Run Job `quality-agent`, daily scheduler at 08:00 UTC)
   scores recent root-agent sessions with the LLM judge, matched
   against the golden eval spec (scope + ground truth; full
   expected-answer grading on the BigQuery path lands with SDK #358),
   and files labeled GitHub issues for failures.
3. **Learn** — an evolution job reads the failing traces — run it
   on demand (a scoped run takes ~10-15 minutes), let accumulating
   quality issues trigger it, or leave the scheduled tick (weekly by
   default, one env var to change). The job
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

## Prerequisites

Everything one-time lives here — from an empty GCP project and empty
repo to a verified environment; every run section after this assumes
it. Local-only usage needs 2; the GCP loop needs all of it.

### 1 — First time only: create the project and the repo

Skip this whole part if the GCP project and the repo already exist.

```bash
# GCP project + billing
gcloud projects create <YOUR_PROJECT_ID>
gcloud billing projects link <YOUR_PROJECT_ID> --billing-account=<BILLING_ACCOUNT_ID>
# find the billing account id: gcloud billing accounts list
gcloud billing projects describe <YOUR_PROJECT_ID> --format="value(billingEnabled)"

# GitHub repo with this code
gh repo create <YOUR_GITHUB_USER>/<YOUR_REPO> --public --clone
# copy this project's files in (or clone your fork), then:
git add -A && git commit -m "Bootstrap: initial import" && git push origin main
# the CI gate triggered by this push goes green only after 4 — expected.
```

Should print `True`.

### 2 — Local machine: tools, auth, environment

#### Tools and auth

- A Google Cloud project with Vertex AI API enabled
- `gcloud` CLI installed and authenticated:
  ```bash
  gcloud auth login
  gcloud auth application-default login
  gh auth login
  ```
- `uv` installed ([Python package manager](https://docs.astral.sh/uv/))

#### Configure `.env`

```bash
export PROJECT_ID="<your-actual-project-id>"
sed -e "s/<YOUR_PROJECT_ID>/$PROJECT_ID/g" .env.example > .env
```

Generates `.env` from the template with your project id substituted —
no manual editing. The rest of the defaults work out of the box.

#### Python environment

```bash
bash scripts/local/local_setup.sh
```

Syncs Python dependencies with `uv`, verifies GCP auth, and tests
that all agent modules import correctly.


### 3 — GCP: deploy the stack


Full deployment to Cloud Run + Agent Engine. Takes ~25 minutes on
first deploy, faster on subsequent runs.

#### 3.1 — GCP infrastructure

```bash
source .env
gcloud config set project $PROJECT_ID
bash scripts/setup/setup_gcp.sh
```

This enables required GCP APIs (Vertex AI, Cloud Run, BigQuery, etc.),
creates the BigQuery dataset for Agent Analytics, seeds the Skill
Registry with the V0 skills, and grants IAM permissions.

#### 3.2 — Deploy all six components

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



> **First deploy note:** On a fresh project, the first Agent Engine
> deploy may fail with "failed to start and cannot serve traffic."
> This is a known race condition -- re-run `deploy_gcp.sh` and it
> will succeed.

#### 3.3 — Smoke test

One test per component: the supervisor test exercises the full
chain (routing, A2A, specialist answer); the two specialist tests
call each Cloud Run service directly.

##### 3.3.a — knowledge_supervisor (Agent Engine, end-to-end)

Tests the full chain: Vertex REST discovery -> Agent Engine session ->
supervisor (skill loaded) -> streamed response.

What to expect: a DEFLECTION — this is the seeded V0 defect, live.
The question is a policy question; the answer sits in policy_agent's
documents one A2A hop away (3.3.b proves it). V0 never takes the
hop: `Routed to: direct`, `Tools: (none)`, "contact HR". Balance
questions DO route (ask "How many PTO days do I have left?" and the
Tools line shows hr_calculator) — the defect is policy questions
only, and it is what the evolution fixes.

```bash
bash scripts/test/smoke_test_deployed.sh -q "What is the meal reimbursement limit?"
```

Expected:

```text
==========================================
  TARGET PROJECT: <PROJECT_ID>
==========================================
Discovering Reasoning Engine 'knowledge-supervisor' in <PROJECT_ID>/us-central1...
Found: projects/<PROJECT_NUMBER>/locations/us-central1/reasoningEngines/<ENGINE_ID>

─────────────────────────────────────────
Q: What is the meal reimbursement limit?
─────────────────────────────────────────
  Routed to:  direct
  Model:      gemini-3.1-flash-lite
  Tools:      (none)
  Tokens:     supervisor 298→19 over 1 model turn(s) (thinking: 0)

  A: I do not have information regarding meal reimbursement limits.
     Please contact HR for assistance with this question.

  Latency: 1.6s
```

Output:
* `Found` — the deployed supervisor (reasoning engine) the script discovered
* `Routed to` — the specialist the supervisor picked; `direct` means it
  answered itself, no A2A hop
* `Model` — the model the supervisor ran this turn on
* `Tools` — tool calls made during the turn; `(none)` on a policy
  question is the V0 defect showing
* `Tokens` — prompt→answer token counts for supervisor and sub-agent;
  thinking tokens listed separately
* `A` — the final answer returned to the user
* `Latency` — end-to-end time for the turn

Another question with proper routing:

```bash
bash scripts/test/smoke_test_deployed.sh -q "How many PTO days do I have left?"
```

```text
==========================================
  TARGET PROJECT: <PROJECT_ID>
==========================================
Discovering Reasoning Engine 'knowledge-supervisor' in <PROJECT_ID>/us-central1...
Found: projects/<PROJECT_NUMBER>/locations/us-central1/reasoningEngines/<ENGINE_ID>

─────────────────────────────────────────
Q: How many PTO days do I have left?
─────────────────────────────────────────
  Routed to:  hr_calculator
  Model:      gemini-3.1-flash-lite
  Tools:      hr_calculator
  Tokens:     supervisor 647→46 over 2 model turn(s) (thinking: 0)

  A: You have 7.8 PTO days left. You also have 4.8 sick leave days remaining.

  Latency: 5.3s
```

##### 3.3.b — policy_agent (Cloud Run, direct A2A)

This test skips the supervisor and talks to the policy agent
directly. It does two things: downloads the agent's A2A card — the
list of skills the agent publishes so other agents know what it can
do — and then sends the question straight to the agent.

What to expect: the CORRECT answer to the exact question the
supervisor just deflected. This agent looks it up in the policy
documents with `lookup_company_policy`. That is the discrepancy the
demo is built on: the knowledge exists one A2A hop away, and V0
never takes the hop.

```bash
bash agents/enterprise/policy_agent/send_query.sh -q "What is the meal reimbursement limit?"
```

Expected:

```text
==========================================
  TARGET PROJECT: <PROJECT_ID>
==========================================
Discovering policy-agent in <PROJECT_ID>/us-central1...
Service URL: https://policy-agent-<HASH>-uc.a.run.app

Checking A2A agent card...
  Agent: policy_agent
  Skills: model, lookup_company_policy, get_current_date

─────────────────────────────────────────
Q: What is the meal reimbursement limit?
─────────────────────────────────────────
Meals are reimbursed up to $75/day during business travel.

Latency: 1.9s
```

##### 3.3.c — hr_calculator (Cloud Run, direct A2A)

Same direct test for the math specialist.

What to expect: a number, computed by the `calculate_pto_details`
tool. The balance accrues from a demo start date, so the exact value
changes from day to day. Ask the supervisor the same question and
its Tools line shows `hr_calculator` — balance routing works at V0.

```bash
bash agents/enterprise/hr_calculator/send_query.sh -q "How many PTO days do I have left?"
```

Expected:

```text
==========================================
  TARGET PROJECT: <PROJECT_ID>
==========================================
Discovering hr-calculator in <PROJECT_ID>/us-central1...
Service URL: https://hr-calculator-<HASH>-uc.a.run.app

Checking A2A agent card...
  Agent: hr_calculator
  Skills: model, calculate_pto_details

─────────────────────────────────────────
Q: How many PTO days do I have left?
─────────────────────────────────────────
You currently have 7.8 PTO days left. You also have 4.8 sick leave days available. You will accrue an additional 10.0 PTO days and 5.0 sick leave days by the end of the year.

Latency: 2.3s
```


#### 3.4 — Connect Gemini Enterprise (optional)

Gemini Enterprise provides a chat UI that connects directly to the
deployed Agent Engine -- no custom frontend needed.

* a. Go to [Gemini Enterprise](https://console.cloud.google.com/gemini-enterprise)in the GCP Console
* b. Create a new **Gemini Enterprise app** (requires a Gemini Enterprise  license -- a trial works)
* c. Navigate to **Agents** > **Add Agent** > **Custom agent via Agent Engine**

* d. Paste the reasoning-engine path — print it with:

   ```bash
   bash scripts/test/smoke_test_deployed.sh -q "How many PTO days do I have left?"
   ```

   Then
   give the agent a user-facing display name — e.g.
   **HR Policy Assistant** — and a description, e.g.:
   *"Answers questions about company policies — PTO, sick leave,
   remote work, expenses, holidays, and benefits — and calculates PTO
   balances and working days. Ask in plain language, e.g. 'How many
   PTO days do I have left?'"*
   The description is shown to employees in the app and helps them
   understand what the agent can do. This registered agent IS the
   `knowledge_supervisor` root agent; the display name is purely what
   employees see in the picker (internal agent names stay hidden).
   Leave **Authorization** empty — it is for agents that act on the
   END USER's behalf against other services (per-user OAuth); this
   agent uses only its own service identity.
* e. Open the app's web URL and select the display name you chose from
   the agent picker

### 4 — GitHub: CI + bot wiring


Follow **[GITHUB_APP_SETUP](docs/GITHUB_APP_SETUP.md)** (PR credential, optional bot identity, one setup-script run).


### 5 — Verify everything: one command

```bash
bash scripts/setup/verify_setup.sh
```

Runs every setup check (tools, auth, `.env`, both Cloud Run services,
the Agent Engine supervisor, jobs + schedulers, Skill Registry, repo
variables, PR credential, bot identity, gate status, branch
protection) and prints one `[PASS]`/`[FAIL]` line per check with the
fix command on failures. Expected:

```text
[PASS] 0.1 tools: gcloud gh uv bq jq
[PASS] 0.2 GCP auth + ADC (<you>)
...
[PASS] 0.12 branch protection (requires: Golden Eval,Load Test)

==========================================
RESULT: 17 passed, 0 failed
==========================================
```

All green -> Step 1 is done. 

## Run the Demo

Two ways to run it:

- **One command** — fire the whole loop and read the results
  ([below](#the-one-command-run)).
- **Step by step** — walk every stage yourself, with a verification
  after each ([the walkthrough](#the-step-by-step-walkthrough),
  Steps 1-7).

### The one-command run

The learning loop is identical everywhere: generate adversarial
traffic against the weak V0 skill, judge every conversation against
golden ground truth, send one analyst per failure, consolidate their
patches into competing candidate skills, validate each candidate on
replayed traffic, keep the best. Where it runs decides how the
winner goes live:

| | Local | Deployed |
|---|---|---|
| Agents | Python processes on this machine | the live stack (Agent Engine + Cloud Run) |
| Failures come from | traffic generated during the run, auto-labeled `demo_run=<run-folder>` (its own BigQuery slice) | BigQuery traces of the deployed agents |
| Winning skill | written to the local `SKILL.md`; the PR is produced as a local artifact — branch + `pr_preview.md` in the run dir, nothing pushed | pushed to the Skill Registry and opened as a PR |
| Safety | none — it is a sandbox | CI gate on the PR; a human merge activates it |

Independent of where it runs, pick one of three PROFILES — how much
time you have vs what the numbers must prove:

| | Lite | Standard | Full |
|---|---|---|---|
| Wall time (measured locally) | **~17 min** | ~30-40 min | ~1-2 h |
| Questions | 13 (1 per category) | 25 (2 per category) | 55 + held-out test split |
| Candidates | 2 | 3 | agent-decided (up to 5) |
| Rounds | 1 | 1 | agent-decided |
| Evolved agent | supervisor only | supervisor only (`EVOLVE_TARGET` overrides) | agent-decided (all bottlenecked agents) |
| Final numbers from | validation set itself | validation set itself | DISJOINT held-out test set |

Caveats:

- **Lite**: each question is worth ~7.7pp, so rates are chunky and
  two close candidates can swap ranks; one agent is evolved; the
  improvement you see is directional, not quotable. Right for first
  contact and every iteration loop.
- **Standard**: steadier rates (~4pp per question), better candidate
  ranking, still no held-out set — good for comparing skill ideas.
- **Full**: the only profile whose final number carries no
  overfitting asterisk (V0 and the winner are re-scored on questions
  evolution never saw). Run it when the number is the deliverable —
  a writeup, a review, a before/after you will defend.

#### Local

One wrapper per profile; extras pass through to the underlying
script (e.g. `run_standard.sh --candidates 4`):

```bash
bash scripts/demo/skill_evolution/run_lite.sh
```

```bash
bash scripts/demo/skill_evolution/run_standard.sh
```

```bash
bash scripts/demo/skill_evolution/run_full.sh
```

#### Deployed

The winner lands as a real PR; merging it activates the skill. The
lite profile:

```bash
gcloud run jobs execute skill-evolution-agent --region $REGION --wait \
  --args="--full-loop,--mode,supervisor,--rounds,1,--candidates,2,--quick"
```

The same dials select the other profiles: raise `--candidates` for
standard; drop `--args` entirely for full (agent-decided scope —
what the weekly tick runs).

Reference results: V0 (54%) -> V1 (97%) -> V2 (98%) on 205 multi-turn
conversations locally; 21.1% -> 96.0% on the deployed loop's PR #4.
Algorithm lineage: [Trace2Skill](https://arxiv.org/abs/2603.25158),
[AutoSkill](https://arxiv.org/abs/2603.01145) —
[paper analysis](docs/skill-evolution/RESEARCH.md).

### The step-by-step walkthrough

Steps 1-7 run the same loop by hand against the deployed stack, one
stage at a time, each with its own verification: the starting point
(Step 1), labeled traffic (3), the evolution job (4), PR review (5),
merge to activate (6), verify the fix (7), roll back (8).

### Step 1 — The starting point (defined, verifiable)

The BigQuery table holds every conversation from every source — old
demo runs, scheduled traffic, other experiments — and is never
cleaned. Isolation comes from labels instead: Step 2 stamps
`$DEMO_LABEL` on every conversation it generates, and each later
stage selects sessions by that label, so the rest of the table is
invisible to your run. Local runs carry the label inside each
trace's `custom_tags`; deployed runs record it in the `run_labels`
side table; every selector matches both.

1. **Pick the demo label** (one choice, threads the whole demo):

   ```bash
   source .env
   export DEMO_LABEL="experiment=round1"   # any k=v you like
   ```

2. **V0 skills everywhere** — files, registry latest revision, and the
   live agents (this restarts policy + supervisor):

   ```bash
   bash scripts/demo/skill_evolution/rollback_demo.sh
   ```

   Fetch the skill the agents now serve straight from the Skill
   Registry and display it:

   ```bash
   uv run python eval/skill_evolution/registry_sync.py verify-read --agent policy_agent
   ```
   Expected output:

   ```text
   OK: GetSkill(ks-policy-agent) revision=<id> SKILL.md=~800 chars
   --- SKILL.md head ---
   ...
   metadata:
     version: "0"
   ```

   `version: "1"` here means an evolved revision is still newest —
   re-run the rollback.


3.  **Verify the starting point:**

Check what is in BigQuery for the provided label. The label is new,
so its slice must be empty — 0 sessions is the clean starting point,
no matter what else the table holds:

```bash
EVOLUTION_TRACE_LABELS=$DEMO_LABEL bash scripts/test/show_traces.sh
```

Expected output:
```text
+----------+--------+----------+--------+
| sessions | events | earliest | latest |
+----------+--------+----------+--------+
|        0 |      0 |     NULL |   NULL |
+----------+--------+----------+--------+
```

Ping the H&R Agent directly via the HTTP end point:


```bash
bash scripts/test/smoke_test_deployed.sh -q "What is the meal reimbursement limit?"
```

Expect V0 defect behavior: a deflection ("contact HR"). A grounded
$75/day answer means an evolved revision is live — re-run the
rollback.


**Reset the slice.** To delete everything recorded under the current
label — its BigQuery events plus `run_labels` rows, nothing else:

```bash
bash scripts/demo/skill_evolution/cleanup_label.sh $DEMO_LABEL
```

### Step 2 — Generate labeled traffic (the system observes failures)

Send 8 labeled conversations at the deployed V0 supervisor — the
same endpoint real users hit. Their failures are the raw material
the evolution job learns from in Step 3:

```bash
bash scripts/demo/generate_traffic.sh --remote \
  --from-file eval/data/questions/two_defect_evolve.json \
  --limit 8 --label $DEMO_LABEL --concurrency 5
```
- `--remote` — target the deployed Agent Engine supervisor. Drop the
  flag to run the identical demo on the local runner.
- `--from-file` — the set of
  [`55 questions`](eval/data/questions/two_defect_evolve.json) to read from.
- `--limit 8` — run only the first 8 questions. One question = one
  conversation = one BigQuery session. Omitted, all 55 run.
- `--label $DEMO_LABEL` — stamps every conversation to create a
  labeled slice: deployed runs record it in the `run_labels` side
  table, local runs carry it inside each trace's `custom_tags`;
  every selector matches both.

While the run streams you'll see each simulated user turn logged
with a strategy tag, e.g. `Simulator [CORRECTION]: Actually, my
onboarding packet says...`:

- The tags — `FOLLOWUP` (next question), `SPECIFICS` (press for
  exact numbers), `VERIFY` (ask to check the policy), `CORRECTION`
  (push back with a golden fact), `END` (done) — are the simulator's
  own per-turn decisions; `END` is what closes a conversation.
- Because the simulator must decide its strategy anyway, the tag is
  ground truth and costs nothing; the `correction_rate` /
  `verify_rate` printed at the end of the run come straight from it.
- The quality report can also tag turns with an LLM pass
  (`--tag-turns`). That is inference — one judge call per turn, and
  it can misread a polite correction — but it works on organic
  traffic that arrives untagged. Rule of thumb: generated traffic
  keeps its generator tags; real user traffic gets report-side
  tagging; when comparing the two on one dashboard, tag both with
  the report path so the bias is uniform.

Expected in the log — the label confirmed at start, the side-table
write at the end:

```text
=== Batch Traffic (remote (deployed)) ===
  Questions:   eval/data/questions/two_defect_evolve.json (limit: 8)
  Concurrency: 5
  Max turns:   4
  Labels:      experiment=round1
  Output:      eval/runs/2026-07-20_205629/traffic.json
...

============================================================
Q: How often can I work from home each week?
   Flow: FOLLOWUP → CORRECTION → END
   Turns: 4, Tools: 1, Corrections: 1, Verifications: 0
   👤: How often can I work from home each week?
   🤖: You can work remotely up to 3 days per week with manager approval.
   👤 [FOLLOWUP]: That's clear, thank you! What are the core hours I need to be available when working remotely?
   🤖: I do not have information about core hours. Please contact HR for details on this.
   👤 [CORRECTION]: I know that core hours are 10am-3pm. Can you confirm this information?
   🤖: I cannot confirm this information. As I mentioned, I do not have information about core hours. Please contact HR for details on this.
   👤 [END]: Thanks, that helps!

============================================================
  MULTI-TURN CONVERSATION RESULTS
============================================================
  Conversations:     8
  Duration:          107.6s
  Avg user turns:    2.8
  Avg tool calls:    0.5
  Corrections:       2 (25.0% of conversations)
  Verifications:     2 (25.0% of conversations)
  Errors:            0
============================================================
20:58:28 [INFO] Recorded labels for 8 deployed sessions in skill-evolution-lab.agent_logs.run_labels: {'run_id': '20260720-205631', 'traffic_source': 'generator', 'experiment': 'round1'}
20:58:28 [INFO] Results saved to eval/runs/2026-07-20_205629/traffic.json
```

To retrieve the new traces:
```bash
bash scripts/test/show_traces.sh                      
EVOLUTION_TRACE_LABELS=$DEMO_LABEL EVAL_TIME_PERIOD=6h \
  bash scripts/test/show_traces.sh         
```


### Step 3 — Run the evolution job (learn + propose)

```bash
gcloud run jobs execute skill-evolution-agent --region $REGION --wait \
  --args="--full-loop,--trace-labels,$DEMO_LABEL,--mode,policy_agent,--rounds,1,--candidates,2,--quick"
```

- `--full-loop` — the whole pipeline in one execution: fetch traces,
  judge, analysts, candidates, registry push + PR.
- `--trace-labels $DEMO_LABEL` — binding: evolve ONLY on your labeled
  slice; the selector lands in `trace_selector.json` and the PR body.
- `--mode policy_agent` — evolve just this agent, and skip the ~5-min
  bottleneck classification (you already named the target).
- `--rounds 1` — one evolution round, no agent-decided round 2.
- `--candidates 2` — two competing skills, best one wins. Each extra
  candidate costs a full validation replay (several minutes); 2 is
  the lightweight demo setting, 3+ buys better odds.
- `--quick` — 25-question validation set and a proportionate failure
  threshold; conversation depth (4 turns) and models stay
  production-grade.
- `--wait` — stream until the job finishes; drop it to run async.

Drop all args for the full agent-decided run (~3 h — what the weekly
tick and the issue-threshold dispatcher execute; cadence is set via
`EVOLUTION_SCHEDULE`).

Inside one run:

| Stage | What happens |
|-------|--------------|
| Pre-flight | Builds a quality report from real BigQuery traces (`QUALITY_SOURCE=bigquery`); falls back to generated traffic below `MIN_SESSIONS` |
| Gate | Proceeds only when there are enough failures to learn from |
| Bottleneck | Classifies each failure by source agent and picks which skill(s) to evolve |
| Evolution | Error analysts study the failures, propose patches, and best-of-N candidate skills are scored on the evolve set |
| Publish | The winning skills are pushed to the Skill Registry as new revisions |
| Regression gate | Failures the winning skill RESOLVED are extracted into `eval_cases.json` + `golden_evals.json` (capped, deduped) — the CI gate grows each cycle, so a future skill that re-breaks them cannot merge |
| PR | A pull request with the evolved `SKILL.md` AND the new regression cases opens on the repo (token-cloned inside the job container) |

### Step 4 — Review the PR (learning as an artifact)

The PR body carries the baseline quality numbers; the diff is the
evolved skill plus any regression cases extracted from failures this
skill resolved (they parametrize straight into the gate tests, so the
PR's own CI run already exercises them). CI runs the Eval & Load Test Gate on it, and the
gate is version-aware: skills at version 0 are held to baseline
expectations, while an evolved skill (version >= 1) must pass the full
routing, fan-out, and quality assertions.

The gate has teeth. In live runs, evolved supervisor skills repeatedly
scored 78-86% on the evolve set by copying observed facts into their
own summary and answering directly -- which broke the routing contract,
so the gate refused them. A refused candidate stays in the registry
history and in the PR record; the next evolution round learns from a
wider window.

**What a refusal looks like on GitHub.** The Actions tab shows a red
"Eval & Load Test Gate" run on the PR's `skill-evolution/*` branch, and
branch protection blocks the merge. That red run is the point: it is
the audit record of why a skill was denied deployment. Close the PR to
retire it (the red run stays in history), or fix and push to the PR
branch to re-adjudicate. Red on main, by contrast, is always a real
problem -- with one caveat: the gate shares the project's model quota
with deploys and evolution jobs, so a gate run that overlaps one can
fail on RESOURCE_EXHAUSTED; re-run it once the project is quiet.

**Two layers keep refused-class skills in check:**

- **In-run pre-check** -- when the evolution job scores a supervisor
  candidate, it runs the same routing/fan-out asserts the gate will run
  on the PR (`score_candidate` -> `_golden_gate_check`). A candidate
  that fails has its score zeroed, so best-of-N selection drops it
  before a PR ever opens.
- **CI gate on the PR** -- the independent adjudication, version-aware:
  evolved skills (version >= 1) face the full hard assertions.

**Scoping a run is binding.** `--mode <agent>`, `--rounds N`, and
`--candidates N` are enforced at the tool layer (env vars
`EVOLUTION_TARGET_AGENTS`, `EVOLUTION_MAX_ROUNDS`,
`EVOLUTION_CANDIDATES`), so the orchestrating agent can neither widen
the target set, add rounds, nor grow the candidate pool beyond what
you asked for.

### Choosing which traces to evolve on (labels)

Every BigQuery event carries `custom_tags` — but WHO stamps them
depends on who logs the event, because plugin tags are fixed at agent
startup:

- **Deployed traffic** (through Agent Engine) is logged by the
  *agents'* plugins: `agent_version` (skill frontmatter) +
  `sw_version` (git sha) + whatever `TRACE_LABELS` the deploy set.
  Per-run labels cannot be attached from the outside; slice deployed
  traffic by version + time window (or redeploy with a label).
- **Local-runner traffic** (`--local`, also used by candidate scoring)
  is logged by the *generator's* plugin, which adds
  `traffic_source=generator` and a per-invocation `run_id`
  (verified live: seed -> `run_id` queryable in BigQuery ->
  `--trace-labels run_id=...` selects exactly that slice). Add your
  own with `TRACE_LABELS="k=v,k2=v2"`.

The evolution job selects its input slice with the same vocabulary:

```bash
# Re-run the scheduled job on demand (default selector: current version)
gcloud scheduler jobs run skill-evolution-weekly --location $REGION

# Evolve on ONE labeled slice — e.g. exactly the traffic you just seeded
uv run python -m agents.workflow.traffic_generator.main \
  --from-file eval/data/questions/two_defect_evolve.json --concurrency 2
# (the run prints its run_id label)
gcloud run jobs execute skill-evolution-agent --region $REGION --wait \
  --args="--full-loop,--trace-labels,run_id=<that run_id>,--mode,policy_agent,--rounds,1,--quick"
```

**Verify before you evolve** — preview exactly what the pre-flight
will fetch (same env vars the job reads), or see the label
distribution of everything in the table:

```bash
bash scripts/test/show_traces.sh                # label distribution
EVOLUTION_TRACE_LABELS=run_id=<id> EVAL_TIME_PERIOD=24h \
  bash scripts/test/show_traces.sh   # the exact slice, with sample sessions
```

The selector (window, version, labels, app) is written to the run
directory and printed in the PR body, so every evolved skill records
exactly which traces taught it. This replaces per-round tables: one
table, label-sliced, and longitudinal quality-by-version queries stay
intact.

### Step 5 — Merge to activate

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

### Step 6 — Verify the fix (the payoff)

The question that deflected in Step 1 now gets the grounded answer:

```bash
bash scripts/test/smoke_test_deployed.sh -q "What is the meal reimbursement limit?"
# Step 1 (V0): "...please contact HR"
# Now (v1):    "$75/day during business travel..."
```

Also confirm the agents fetched the merged revision:

```bash
gcloud logging read 'textPayload:"Loaded skill from registry"' \
  --project=$PROJECT_ID --freshness=15m --limit=4
```

### Step 7 — Roll back (back to the Step 1 state)

```bash
bash scripts/demo/skill_evolution/rollback_demo.sh
```

Resets the `SKILL.md` files to V0, republishes V0 to the Skill Registry
as the newest revision (the registry is append-only, so the evolved
revisions stay in history), restarts the policy agent and supervisor so
they serve V0 immediately, and prints the verification. Flags:
`--baseline stub|two-defect` (default `two-defect`) and
`--skip-redeploy` (agents pick up V0 on their next restart instead).

## Alternative: Local-Only Demo (no deployment)

Run the full skill evolution pipeline on your machine. No GCP
deployment needed -- only Vertex AI API access for Gemini models.

One-time setup lives in [Prerequisites](#step-0--setup--prerequisites).

The run profiles and commands live in
[The one-command run](#the-one-command-run); everything below is
about what a local run produces and how to work with it.

### What to expect

| Version | Meaningful Rate | What happened |
|---------|----------------|---------------|
| V0      | ~54-60%        | Baseline: minimal skill, agent redirects to HR for most questions |
| V1      | ~80-97%        | Evolution adds keyword mappings, anti-hallucination rules, scope boundaries |
| V2      | ~95-98%        | Refinement: edge cases, format improvements |

V0 -> V1 is the key jump. The evolved skill gains structured sections
(Tool Usage, Anti-Patterns, Out-of-Scope, Keyword Mappings) that the
V0 baseline lacks entirely.

**Reusing the V0 baseline.** The demo's first phase measures how bad
V0 is: send traffic at the V0 skill, judge every conversation,
produce the "before" numbers. That result barely changes between
runs — V0 fails the same way every time — so on repeat runs you can
skip re-measuring it. The startup banner shows which mode you are in
(`Reuse V0: false` = fresh baseline, the default; `true` = borrowed):

```bash
bash scripts/demo/skill_evolution/run_full.sh --reuse-v0
```

`--reuse-v0` takes the V0 traffic and quality report from a previous
run (`--resume <run-dir>` picks which; without it, the pre-built
reference baseline) and spends the saved ~20 minutes on the part
that changes: evolution and the V1 proof. First run: leave the
default, so before and after come from the same session and model.
Iterating on evolution: add the flag. One label caveat: borrowed V0
traffic keeps its original run's `demo_run` label — only the newly
generated conversations carry this run's label.

### Reading the output

Every run writes to `eval/runs/<timestamp>_demo_<mode>/`. Start with
`SUMMARY.md` — the run's slice label, whether anything was published
(local runs: no), a quality table for every version, and which
version the PR preview carries. From there:

- `run.log` — everything the run printed, including the slice label
- `v0_quality_report.md` — the judged baseline, failure by failure;
  these failures are the evolution's input
- `_score_candidate_N_report.json` — each candidate's replay score;
  the best one becomes the next version
- `vN_*_skill.md` — the evolved skill text per version. Read these:
  the diff against V0 IS the learning, in plain markdown
- `pr_preview.md` — the PR as a local artifact: metrics table,
  summary of changes, diff, and the two commands that publish it
- `TRIAGE.md` — failures split into what evolution fixed vs what it
  cannot fix (tool bugs -> ENG, missing facts -> KNOWLEDGE)

The live `SKILL.md` files are restored to V0 when the run ends; the
run dir keeps every evolved version. A later round can score WORSE
than an earlier one (the agent explores) — the preview always carries
the best-measured version, and `SUMMARY.md` shows the full curve.

### Resetting between runs

The run already restores the local `SKILL.md` files to V0 when it
ends. For a guaranteed-clean slate — files, Skill Registry newest
revision, and the live agents all back to V0 — run the same rollback
the deployed demo uses:

```bash
bash scripts/demo/skill_evolution/rollback_demo.sh
```

Optionally delete a finished run's BigQuery slice (label printed in
the run's `SUMMARY.md`):

```bash
bash scripts/demo/skill_evolution/cleanup_label.sh demo_run=<run-folder>
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

Each stage of the local pipeline, run individually. Everything
writes into one run folder:

```bash
source .env
RUN_DIR="eval/runs/$(date +%Y-%m-%d_%H%M%S)_evolution" && mkdir -p "$RUN_DIR"
```

**1. Start from the V0 baseline skill** — the deliberately minimal
skill is the permanent backup next to the live one:

```bash
cp agents/enterprise/policy_agent/skill/SKILL.v0.md \
   agents/enterprise/policy_agent/skill/SKILL.md
```

**2. Generate adversarial traffic** — the simulated user asks the
questions and, knowing the golden facts, pushes back on wrong answers
(multi-turn):

```bash
bash scripts/demo/generate_traffic.sh \
    --from-file eval/data/questions/demo_quick.json \
    -o "$RUN_DIR/v0_traffic.json" --concurrency 10
```

**3. Judge every conversation** — golden-matched ground truth (see
"The single input" above); output partitions sessions into successes
and failures:

```bash
bash scripts/demo/skill_evolution/score.sh \
    -i "$RUN_DIR/v0_traffic.json" \
    -o "$RUN_DIR/v0_quality_report.json" --report
```

The printed summary shows `meaningful_rate`, `unhelpful_rate`, and
the failure count.

**4 + 5. Analysts, patches, consolidation, best-of-N** — one command
runs the whole evolution stage: an analyst per failure (each
investigates with tool access), patch scoring, consolidation into
candidate `SKILL.md` documents, and empirical scoring that keeps the
best candidate:

```bash
uv run python agents/workflow/skill_evolution_agent/main.py \
    --report "$RUN_DIR/v0_quality_report.json"
```

Artifacts land in `$RUN_DIR/*_candidates/`; the winning skill is
deployed to `agents/enterprise/policy_agent/skill/SKILL.md`.

**6. Re-score and compare** — fresh traffic against the evolved
skill, then the before/after table:

```bash
bash scripts/demo/generate_traffic.sh \
    --from-file eval/data/questions/demo_quick.json \
    -o "$RUN_DIR/v1_traffic.json" --concurrency 10
bash scripts/demo/skill_evolution/score.sh \
    -i "$RUN_DIR/v1_traffic.json" \
    -o "$RUN_DIR/v1_quality_report.json" --report
uv run python eval/scoring/score_conversations.py --compare \
    "$RUN_DIR/v0_quality_report.json:V0" \
    "$RUN_DIR/v1_quality_report.json:V1"
```

Repeat the traffic->score->evolve stages for a V2 round (the gate
keeps V2 only when it beats V1). For a narrated walkthrough with
pauses, see [Demo Script](docs/skill-evolution/DEMO_SCRIPT.md).

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
            +--------+---------------+
            |  Benefits Agent        |   skill-only today:
            |  SKILL.md (in-process  |   in-process locally,
            |  locally; Cloud Run    |   Cloud Run service
            |  service = backlog)    |   pending
            +--------+---------------+
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

### How a question flows (Agent Engine, AgentTool, A2A)

Three pieces of vocabulary, then the lifecycle:

- **Vertex AI Agent Engine** is the managed runtime hosting the root
  agent: it owns sessions (multi-turn memory), scaling, and the
  `stream_query` API that clients call. The supervisor lives here so
  conversations survive across turns without any server of our own.
- **A2A (Agent2Agent protocol)** is the open HTTP protocol agents use
  to call each other. Each specialist is an independent Cloud Run
  service exposing an A2A endpoint with an agent card describing what
  it can do — the supervisor talks to specialists the same way any
  external agent could.
- **AgentTool** is the ADK wrapper that presents a whole remote agent
  to the supervisor's LLM as a callable tool. Routing therefore IS
  tool-calling: the model picks specialists the way it picks any tool,
  which lets it call several in a single turn.

Lifecycle of one compound question ("Compare my meal limit with the
HSA contribution"):

1. The client calls the supervisor's Agent Engine endpoint
   (`stream_query`) inside a session.
2. `knowledge_supervisor`'s LLM reads its `SKILL.md` (fetched from the
   Skill Registry at startup) and plans: this needs `policy_agent`
   (meal limit) AND `benefits_agent` (HSA).
3. It emits two AgentTool calls. Each becomes an A2A HTTP request to
   that specialist's Cloud Run service.
4. Each specialist is a full ADK agent of its own: it loads its own
   `SKILL.md`, runs its own LLM turn, calls its own tools
   (`lookup_company_policy`, calculators), and returns its answer over
   A2A.
5. The supervisor synthesizes the specialist answers into one response
   and streams it back.
6. Every hop — supervisor turns, tool calls, specialist sessions — is
   logged to BigQuery by the analytics plugins, version- and
   label-tagged. This trace is what the quality and evolution agents
   read.

Why this topology: specialists deploy, scale, and **evolve
independently** (each has its own SKILL.md and registry entry);
failures surface at an ownership boundary (the bottleneck stage
attributes each failure to supervisor routing vs a specialist's
knowledge); and the supervisor stays thin — a router with conventions
rather than an agent that knows everything.

### The evolution loop (end to end)

```text
 (1) traffic                     (2) traces
 users / simulator --> supervisor --> BigQuery agent_events
                                      (tagged agent_version)
                                              |
                               (3) trigger: on-demand | issues | schedule
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
| skill_evolution_agent | Cloud Run Job | on-demand (`gcloud run jobs execute`), quality-issue threshold, or scheduled tick (default: weekly) |
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
- **skill_evolution_agent** — the healer (Cloud Run Job; triggered
  on demand, by quality-issue threshold, or by its scheduled tick —
  weekly by default). One run: quality report from BigQuery → failure-count
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

### The full cycle, actor by actor

Every stage of the loop, who runs it, and how to watch it live:

| Stage | Actor (code) | Trigger | Reads | Writes | Watch it |
|---|---|---|---|---|---|
| Serve | `knowledge_supervisor` (Agent Engine) + `policy_agent`/`hr_calculator` (Cloud Run, A2A) | user / API call | Skill Registry (SKILL.md at startup), tools | the answer | `bash scripts/test/smoke_test_deployed.sh` |
| Observe | BigQuery Analytics plugins (in each agent) | every event | — | `agent_logs.agent_events`, tagged version + labels | `bash scripts/test/show_traces.sh` (label distribution / selector preview) |
| Detect | `quality_agent` (Cloud Run Job) | daily 08:00 UTC scheduler, or `gcloud run jobs execute quality-agent` | BQ window, golden eval spec | quality report (GCS) + labeled GitHub issues | `gh issue list`; job logs |
| Learn | `skill_evolution_agent` (Cloud Run Job) | on demand / issue threshold / weekly tick | BQ traces (selector), golden spec | evolved SKILL.md candidates, scores, regression cases | the 10-step table in [Demo Variants](#demo-variants--what-runs-what-is-cut-and-why) |
| Propose | same job, final stage | end of a successful run | run artifacts | Skill Registry revision + the PR (skill + eval cases + selector) | `gh pr list` |
| Adjudicate | Eval & Load Test Gate (GitHub Actions) | the PR | repo skills at PR state | green/red checks; branch protection blocks red | `gh pr checks <n>` |
| Activate | Deploy to GCP workflow (GitHub Actions, WIF) | PR merge | merged repo | registry sync + redeploy; agents fetch the new revision | `gcloud logging read 'textPayload:"Loaded skill from registry"'` |
| Roll back | `rollback_demo.sh` | you | SKILL.v0 files | V0 as newest registry revision; agents restarted | script prints verification |

### The one manual input: Golden Q&A

Golden Q&A (`eval/data/golden_evals.json`) is a list of curated
entries: a question, its `expected_answer`, and optionally
`expected_behavior: decline` for topics the agent must refuse.

**How it is used — similarity matching, exactly:** when the judge
scores a conversation, every session question and every golden
question is embedded, and each session is matched to its
nearest golden entry by cosine similarity (threshold 0.92 — high on
purpose, so only true paraphrases match: "How many vacation days do I
get?" matches the PTO entry; a novel question matches nothing). Three
outcomes:

1. **Matched, in scope** — the golden `expected_answer` is injected
   into the judge's prompt, and the response is graded against that
   ground truth. This is what makes correctness scores trustworthy:
   the judge compares against the known-right answer instead of its
   own opinion.
2. **Matched, decline entry** — the judge is told a polite refusal is
   the correct outcome, so out-of-scope questions score as `declined`
   when handled right rather than being punished as unhelpful.
3. **No match (the question is absent from the list)** — the judge
   still scores the session, but as an ungrounded LLM estimate, and
   the report says so explicitly ("LLM estimates WITHOUT ground
   truth"). These sessions also feed the `new-topic` flow: the quality
   agent surfaces questions with no golden coverage and no history as
   issues for a human decision — add a golden entry (and the
   capability) or mark the topic out-of-scope.

The list grows two ways: humans curate entries, and each evolution
cycle extracts resolved failures into new entries automatically — so
coverage tracks what users actually ask.

Golden Q&A feeds three consumers:
- **The user simulator** mirrors these facts to adversarially
  stress-test the agent (it knows the right answer, so it pushes back
  on wrong ones)
- **The LLM Judge** grades against matched entries as described above
- **The evolution engine** works on the pass/fail labels the judge
  produces

## Demo Variants — What Runs, What Is Cut, and Why

### The four ways to run it

| Variant | Command | Time | Use when |
|---|---|---|---|
| Local quick | `bash scripts/demo/skill_evolution/run_lite.sh` | ~17 min | First contact; no deployment (lite profile; run_standard.sh for steadier numbers) |
| Local full | `bash scripts/demo/skill_evolution/run_full.sh` | ~1-2 h | Full local evaluation (55 questions + held-out split) |
| GCP demo run | `gcloud run jobs execute skill-evolution-agent --region $REGION --wait --args="--full-loop,--mode,policy_agent,--rounds,1,--candidates,2,--quick"` | ~30-45 min | Live demo of the deployed loop, warm BigQuery window |
| GCP full run | same, no `--args` (also what the scheduler ticks and quality issues trigger) | ~5-3 h | Production cadence: agent-decided scope, full validation |

### Every step of the GCP demo run

Measured on project `skill-evolution-lab`; "full run" column shows the
same step at production settings for contrast.

| # | Step | What happens | Input | Output (artifact) | Demo time | Full time | Verify |
|---|---|---|---|---|---|---|---|
| 1 | Container start | Cloud Run provisions the job image | — | execution id | ~2 min | ~2 min | `gcloud run jobs executions list --job=skill-evolution-agent` |
| 2 | BQ pre-flight | LLM-judges recent root-agent sessions from `agent_events` (app/version/label-filtered) | BigQuery window (`EVAL_TIME_PERIOD`, selector) | `v0_quality_report.json` + `trace_selector.json` in the run dir | ~2.5 min | ~3-15 min | BEFORE the run: `bash scripts/test/show_traces.sh` previews the exact slice; during: job log `Pre-flight quality report from BigQuery: N sessions` |
| 3 | Evolution gate | Proceed only if failures >= threshold | the report | go / no-go log line | seconds | seconds | log: `should_evolve: True, failures: N` |
| 4 | Bottleneck attribution | Classifies each failure to the responsible agent | failures | recommendation | **skipped** (target named on the CLI — classifying would re-derive the answer) | ~5 min | log: `Skipped classification: EVOLUTION_TARGET_AGENTS=...` |
| 5 | Analyst fleet | One agent per failure investigates the trace (tool access) and proposes a patch | failure trajectories | patch list (`3*_...` artifacts) | ~1 min | ~6 min | log: `[k/N] [error] ... -> patch` |
| 6 | Consolidation | Merges patches into N candidate `SKILL.md` docs (best-of-N) | patches | `*_candidates/candidate_*.md` | ~1 min | ~7 min | log: `Best-of-N complete` |
| 7 | Candidate validation | Each candidate is deployed to a local supervisor and scored on replayed traffic | candidates + question set | `_score_candidate_*_report.json` per candidate | ~2 min x 3 | ~12 min x 5 | log: `Candidate k scored X% meaningful` |
| 8 | Regression extraction | Failures the winner RESOLVED become new gate cases | baseline + winner reports | `regression_cases.json` + updated `eval/data/*.json` | seconds | seconds | log: `Extracted N regression case(s)` |
| 9 | Registry publish | Winning skill becomes a new Skill Registry revision | winning `SKILL.md` | revision id | ~1 min | ~1 min | `registry_sync.py revisions --agent policy_agent` |
| 10 | Pull request | Token-clone, branch, commit skill + eval files, `gh pr create` | run artifacts | the PR | ~2 min | ~2 min | `gh pr list` — title carries baseline% -> evolved% |

### What `--quick` cuts — and what it never touches

| Dial | Full | Quick | Why it is safe to cut | What it costs |
|---|---|---|---|---|
| Validation question set | 55 questions | 25 (2 per category, all 13 categories kept) | Coverage per category is preserved | Coarser scores: each question is worth 4pp, so two close candidates can swap ranks |
| Turns per validation conversation | up to 4 (simulated user pushes back) | up to 4 — not cut | Full conversation depth is kept: deflection (turn 1), pushback/parroting (turn 2), drift (turns 3-4) all measured | Quick runs take longer than a 1-turn profile would (~2-3x per candidate) |
| Validation supervisor model | the serving model (gemini-3.1-flash-lite) | same — not cut | Ranking measures exactly what production runs | — |
| Bottleneck classification | runs (~5 min) | skipped when `--mode` names the target | You already gave the answer on the command line | None for a scoped run; scheduled runs (no `--mode`) still classify |
| Rounds / candidates | agent-decided (up to 5 x 5) | bound to your `--rounds`/`--candidates` | Demo needs a bounded runtime | Fewer shots at a better skill per run |

**Never cut, in any variant:** the analyst fleet reads every real
failure from BigQuery (nothing sampled); the judge's scoring
dimensions and golden matching; the CI gate on the PR (full golden
evals + load test); regression extraction; the registry+PR flow; and
the scheduled production run, which uses full settings by default.

## Quality Monitoring & Automated Evolution

After deployment, a closed-loop quality pipeline monitors agent
performance and evolves skills automatically from production data.
Two agents divide the work: a **daily sentinel** that monitors, and a
**healer** that evolves — on demand, on an issue threshold, or on
its scheduled tick.

### Quality Agent -- Daily Sentinel

Runs daily via Cloud Scheduler. Queries BigQuery for recent root-agent
sessions (app-, version-, and label-filtered), scores each with the
LLM judge using the golden eval spec for scope and ground-truth
context (full per-answer grading on the BQ path arrives with SDK
issue #358), and creates labeled GitHub issues for failures
(`--repo` from `GITHUB_REPO`, so it works from the container).

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
bash scripts/demo/skill_evolution/run_lite.sh
```

Or run the six bootstrap stages one at a time against your agent —
the exact commands are in
[Alternative: Local-Only Demo -> Manual step-by-step](#alternative-local-only-demo-no-deployment);
swap the questions file for yours.

For full input schemas and pipeline details, see
[Inputs, Setup, and Pipeline](docs/skill-evolution/ALGORITHM.md#inputs-setup-and-pipeline)
in the algorithm reference.

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
  -- each new quality issue triggers a dispatcher: the runner counts
  open `quality` issues against `EVOLUTION_MIN_OPEN_ISSUES` (repo var,
  default 10) and at the threshold dispatches the skill-evolution-agent
  Cloud Run job (async, via WIF), commenting the issue either way.
  Proven live 2026-07-17: the daily quality agent filed issues at
  08:00, the 10-issue threshold tripped, and the dispatcher started a
  full evolution run with no human in the loop.

Setup guides: [`docs/CI_CD_GITHUB.md`](docs/CI_CD_GITHUB.md) (Workload
Identity Federation, repo variables, branch protection) and
[`docs/GITHUB_APP_SETUP.md`](docs/GITHUB_APP_SETUP.md) (the bot
identity used for issues and PRs).

## Troubleshooting

- **WIF provider NOT_FOUND right after creation** — propagation race;
  `setup_github.sh` retries automatically; re-run if it exhausts
  retries (idempotent).
- **First Agent Engine deploy fails ("failed to start and cannot
  serve traffic")** — known race on fresh projects; re-run
  `deploy_gcp.sh`.
- **Registry seed fails with 403** — check ADC
  (`gcloud auth application-default login`) and that
  `aiplatform.googleapis.com` is enabled (3.1 does this).
- **Gate red with RESOURCE_EXHAUSTED** — fresh-project Vertex quota;
  rerun, request a `gemini-2.5-flash` bump, and avoid pushing while a
  deploy/rollback/evolution run competes for the same quota.
- **Traffic fails with "Quota exceeded ... Query Reasoning Engine
  requests"** — fresh projects allow 90 Agent Engine requests/min
  (sessions + streams share it). The generator backs off; keep
  `--concurrency 2` for deployed seeding, or request an increase on
  `QueryReasoningEngineRequestsPerMinutePerProjectPerRegion`.
- **Evolution job killed at its task timeout** — a full 3-skill
  best-of-5 run needs ~3h; the deploy sets 4h. Prefer the scoped demo
  profile for anything interactive.
- **Evolution job can't open a PR** — the `github-pat` secret is
  missing or expired; see the rotation recipe in
  [docs/GITHUB_APP_SETUP.md](docs/GITHUB_APP_SETUP.md).

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
    run_lite.sh / run_standard.sh / run_full.sh   Profile wrappers (see Local-Only Demo)
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

## Backlog

Measured issues and planned work live in
[docs/BACKLOG.md](docs/BACKLOG.md) — currently headlined by the demo
latency plan (73 min measured -> ~10 min target, with the per-phase
numbers and fixes).

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
