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

## Where to Start

| You want to... | Go to | Time |
|---|---|---|
| Understand the system first | [Architecture](#architecture) | 10 min read |
| See the evolution loop run on your machine (no deployment) | [Run the Demo Locally](#run-the-demo-locally) | ~15 min |
| Stand up the full production loop on GCP from an empty project | [docs/BOOTSTRAP.md](docs/BOOTSTRAP.md), then [Run the Production Loop Demo](#run-the-production-loop-demo) | ~90 min setup, then ~15 min per loop |
| Point the loop at your own agent | [Plug In Your Own Agent](#plug-in-your-own-agent) | ~1 h |

Both demo paths run the same algorithm; the local path trades the
deployed stack (Agent Engine, Skill Registry, BigQuery, auto-PR) for
speed and zero setup.

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

## How Skills Evolve

The system has one manual input: **Golden Q&A** -- curated
question-answer pairs that define what correct behavior looks like.
Everything else is automated.

### The single input

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

### The evolution cycle: from V0 to production quality

This is the SKILL's journey — how a deliberately weak V0 becomes a
production-quality skill through repeated cycles. Setting up the
environment (project, repo, deployment) is a separate, one-time thing:
that lives in [docs/BOOTSTRAP.md](docs/BOOTSTRAP.md) and is only
summarized in the prerequisites row below.

**Prerequisites — one-time setup, before any cycle.** The six steps
below assume a working environment. Set it up once:

| Path | One-time setup | Where |
|---|---|---|
| Local (this section) | GCP project with Vertex AI enabled, `gcloud auth login` + `gcloud auth application-default login`, `uv`, `cp .env.example .env` (set `PROJECT_ID`), then `bash scripts/local/local_setup.sh` | [Run the Demo Locally -> Prerequisites](#run-the-demo-locally) |
| Deployed (GCP loop) | empty project + empty repo -> infra -> CI -> deploy | [docs/BOOTSTRAP.md](docs/BOOTSTRAP.md), Parts A and B |

Everything after this line is the **repeatable evolution cycle** — run
it as many times as you like without touching setup again.

The whole cycle in one command (local, ~15 min quick / ~1-2h full):

```bash
bash scripts/demo/skill_evolution/run_demo.sh --quick   # or --full
```

That script performs the six steps below; run them individually when
you want to inspect each stage. Everything writes into one run folder:

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
uv run python agents/workflow/traffic_generator/main.py \
    --local --local-agents --multi-turn \
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
# printed summary: meaningful_rate, unhelpful_rate, failure count
```

**4 + 5. Analysts, patches, consolidation, best-of-N** — one command
runs the whole evolution stage: an analyst per failure (each
investigates with tool access), patch scoring, consolidation into
candidate `SKILL.md` documents, and empirical scoring that keeps the
best candidate:

```bash
uv run python agents/workflow/skill_evolution_agent/main.py \
    --report "$RUN_DIR/v0_quality_report.json"
# artifacts: $RUN_DIR/*_candidates/, the winning skill deployed to
# agents/enterprise/policy_agent/skill/SKILL.md
```

**6. Re-score and compare** — fresh traffic against the evolved
skill, then the before/after table:

```bash
uv run python agents/workflow/traffic_generator/main.py \
    --local --local-agents --multi-turn \
    --from-file eval/data/questions/demo_quick.json \
    -o "$RUN_DIR/v1_traffic.json" --concurrency 10
bash scripts/demo/skill_evolution/score.sh \
    -i "$RUN_DIR/v1_traffic.json" \
    -o "$RUN_DIR/v1_quality_report.json" --report
uv run python eval/scoring/score_conversations.py --compare \
    "$RUN_DIR/v0_quality_report.json:V0" \
    "$RUN_DIR/v1_quality_report.json:V1"
```

Repeat 2-6 for a V2 round (the gate keeps V2 only when it beats V1).
For the DEPLOYED version of this cycle — real BigQuery traces, the
Skill Registry, auto-PR — follow
[Run the Production Loop Demo](#run-the-production-loop-demo) below;
for a from-empty-project setup, [docs/BOOTSTRAP.md](docs/BOOTSTRAP.md).

Results: V0 (54%) -> V1 (97%) -> V2 (98%) on 205 multi-turn
conversations. Inspired by [Trace2Skill](https://arxiv.org/abs/2603.25158)
and [AutoSkill](https://arxiv.org/abs/2603.01145) -- see
[the paper analysis](docs/skill-evolution/RESEARCH.md).

### Production: monitoring and healing

Once deployed, two workflow agents maintain quality autonomously:
- **Quality Agent** (daily sentinel) scores production sessions
  against Golden Q&A, detects regressions via BigQuery history,
  creates GitHub issues
- **Skill Evolution Agent** (the healer) re-runs the evolution loop —
  on demand, when enough quality issues accumulate, or on its
  scheduled tick (weekly by default) — using real production traces

New topics that Golden Q&A doesn't cover surface as `new-topic` issues
for a human decision: add the capability or mark it out-of-scope.

See [Skill Evolution docs](docs/skill-evolution/) for the full lifecycle
narrative and algorithm details.

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

Each of the six pipeline stages, with its command and artifacts:
[The evolution cycle: from V0 to production quality](#the-evolution-cycle-from-v0-to-production-quality).
For a narrated walkthrough with pauses, see
[Demo Script](docs/skill-evolution/DEMO_SCRIPT.md).

## Run on GCP — One-Time Setup

The complete ordered path from an empty GCP project and empty repo
is **[docs/BOOTSTRAP.md](docs/BOOTSTRAP.md)** — tested end to end;
follow it top to bottom. The subsections below are the reference
details for its two big steps.

### Deploy the stack

Full deployment to Cloud Run + Agent Engine. Takes ~25 minutes on
first deploy, faster on subsequent runs.

#### Step 1: GCP infrastructure

```bash
source .env
gcloud config set project $PROJECT_ID
bash scripts/setup/setup_gcp.sh
```

Enables required GCP APIs (Vertex AI, Cloud Run, BigQuery, etc.),
creates the BigQuery dataset for Agent Analytics, seeds the Skill
Registry with the V0 skills, and grants IAM permissions.

#### Step 2: Deploy

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

#### Step 3: Smoke test

```bash
bash scripts/test/smoke_test_deployed.sh
bash scripts/test/smoke_test_deployed.sh -q "How many PTO days do I have left?"

# Per-agent tests
bash agents/enterprise/policy_agent/send_query.sh -q "How many sick days do I get?"
bash agents/enterprise/hr_calculator/send_query.sh -q "How many PTO days do I have left?"
```

#### Step 4: Connect Gemini Enterprise (optional)

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

### Set up the GitHub repo (CI + bot)

The production loop treats GitHub as part of the runtime: CI gates
every skill change, merges trigger deployment, and the evolution job
opens PRs with a bot credential. One script plus two manual steps wire
all of it.

#### Step 1: Repo and prerequisites

- Fork or create the repo and clone it
- `cp .env.example .env` and set `PROJECT_ID`
- Authenticate the GitHub CLI: `gh auth login`

#### Step 2: Run the setup script

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

#### Step 3: Verify

```bash
gh variable list          # 8 variables, PROJECT_ID = your project
gcloud secrets describe github-pat --project=$PROJECT_ID
gh api repos/{owner}/{repo}/branches/main/protection --jq '.required_status_checks.contexts'
```

Open any PR: the **Eval & Load Test Gate** should start automatically,
and after `scripts/setup/setup_gcp.sh` + a deploy, merging to main
triggers **Deploy to GCP**.

## Demo Variants — What Runs, What Is Cut, and Why

### The four ways to run it

| Variant | Command | Time | Use when |
|---|---|---|---|
| Local quick | `bash scripts/demo/skill_evolution/run_demo.sh --quick` | ~15 min | First contact; no deployment |
| Local full | `bash scripts/demo/skill_evolution/run_demo.sh --full` | ~1-2 h | Full local evaluation (205 questions, V0->V1->V2) |
| GCP demo run | `gcloud run jobs execute skill-evolution-agent --region $REGION --wait --args="--full-loop,--mode,policy_agent,--rounds,1,--candidates,3,--quick"` | ~15 min | Live demo of the deployed loop, warm BigQuery window |
| GCP full run | same, no `--args` (also what the scheduler ticks and quality issues trigger) | ~1.5-3 h | Production cadence: agent-decided scope, full validation |

### Every step of the GCP demo run

Measured on project `skill-evolution-lab`; "full run" column shows the
same step at production settings for contrast.

| # | Step | What happens | Input | Output (artifact) | Demo time | Full time | Verify |
|---|---|---|---|---|---|---|---|
| 1 | Container start | Cloud Run provisions the job image | — | execution id | ~2 min | ~2 min | `gcloud run jobs executions list --job=skill-evolution-agent` |
| 2 | BQ pre-flight | LLM-judges recent root-agent sessions from `agent_events` (app/version/label-filtered) | BigQuery window (`EVAL_TIME_PERIOD`, selector) | `v0_quality_report.json` + `trace_selector.json` in the run dir | ~2.5 min | ~3-15 min | BEFORE the run: `bash scripts/test/show_traces.sh --selector` previews the exact slice; during: job log `Pre-flight quality report from BigQuery: N sessions` |
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
| Turns per validation conversation | up to 4 (simulated user pushes back) | 1 | The deflection defect (the main one) shows in turn 1 | Parroting behavior is NOT measured during candidate RANKING (it needs a turn-2 pushback). Analysts still see every real parroting failure from BigQuery and still patch it |
| Validation supervisor model | gemini-2.5-pro | gemini-2.5-flash | All candidates are scored under identical conditions, so the ranking stays fair | Absolute scores shift slightly vs pro |
| Bottleneck classification | runs (~5 min) | skipped when `--mode` names the target | You already gave the answer on the command line | None for a scoped run; scheduled runs (no `--mode`) still classify |
| Rounds / candidates | agent-decided (up to 5 x 5) | bound to your `--rounds`/`--candidates` | Demo needs a bounded runtime | Fewer shots at a better skill per run |

**Never cut, in any variant:** the analyst fleet reads every real
failure from BigQuery (nothing sampled); the judge's scoring
dimensions and golden matching; the CI gate on the PR (full golden
evals + load test); regression extraction; the registry+PR flow; and
the scheduled production run, which uses full settings by default.

## Guided Walkthrough — Every Step by Hand

The sections above explain the system; this one is the operator's
track: run the entire loop manually, verifying state at every step.
Step 0 is the prerequisites gate; Step 1 defines the exact starting
point. (Steps 2+ follow the loop and are being refined into this
section — for now they continue in
[Run the Production Loop Demo](#run-the-production-loop-demo).)

### Step 0 — Prerequisites, each with its verification

Everything here is one-time. Run every verify; all must pass before
Step 1.

| # | Requirement | Verify with | Expect |
|---|---|---|---|
| 0.1 | Tools | `for t in gcloud gh uv bq jq; do command -v $t >/dev/null && echo "OK      $t" || echo "MISSING $t"; done` | five lines, all `OK` (bq ships inside the gcloud SDK) |
| 0.2 | GCP auth + ADC | `gcloud auth list --filter=status:ACTIVE --format="value(account)"` and `gcloud auth application-default print-access-token >/dev/null && echo ADC-OK` | your account; `ADC-OK` |
| 0.3 | GitHub auth | `gh auth status` | logged in, repo scope |
| 0.4 | `.env` | `grep -E "^(PROJECT_ID|REGION|DATASET_ID|TABLE_ID)" .env` | your project; values match what you deployed with |
| 0.5 | Local Python env | `bash scripts/local/local_setup.sh` | ends all-green (deps, auth, agent imports) |
| 0.6 | Cloud Run services | `gcloud run services list --region=$REGION --format="table(metadata.name,status.conditions[0].status)"` | `policy-agent` and `hr-calculator` both `True` |
| 0.7 | Agent Engine supervisor | `bash scripts/test/smoke_test_deployed.sh -q "How many sick days do I get?"` | a real answer; prints the reasoning-engine path |
| 0.8 | Jobs + schedulers | `gcloud run jobs list --region=$REGION` and `gcloud scheduler jobs list --location=$REGION` | 3 jobs; `quality-agent-daily` + `skill-evolution-weekly` |
| 0.9 | Skill Registry seeded | `source .env && uv run python eval/skill_evolution/registry_sync.py revisions --agent policy_agent` | at least 1 revision |
| 0.10 | CI wiring | `gh variable list` and `gcloud secrets describe github-pat --project=$PROJECT_ID` | 8 vars incl. `WIF_PROVIDER`; secret exists |
| 0.11 | Gate green on main | `gh run list --workflow "Eval & Load Test Gate" --limit 1` | latest main run `success` |
| 0.12 | Branch protection | `gh api repos/{owner}/{repo}/branches/main/protection --jq '.required_status_checks.contexts'` | `["Golden Eval","Load Test"]` |

Anything missing: [docs/BOOTSTRAP.md](docs/BOOTSTRAP.md) is the
ordered path that creates all of it.

### Step 1 — The starting point (defined, verifiable)

The walkthrough starts from this exact state — reset to it any time:

1. **BigQuery empty** (or a fresh table):

   ```bash
   source .env
   bq query --project_id=$PROJECT_ID --use_legacy_sql=false \
     "TRUNCATE TABLE \`$PROJECT_ID.$DATASET_ID.$TABLE_ID\`"
   ```

2. **V0 skills everywhere** — files, registry latest revision, and the
   live agents (this restarts policy + supervisor):

   ```bash
   bash scripts/demo/skill_evolution/rollback_demo.sh
   ```

3. **No leftover evolution artifacts** (optional, for a pristine demo):

   ```bash
   gh pr list    # close old skill-evolution/* PRs you are done with
   gh issue list --label quality   # close or keep; >=10 open will trip the dispatcher
   ```

**Verify the starting point:**

```bash
bash scripts/test/show_traces.sh          # expect: zero rows
bash scripts/test/smoke_test_deployed.sh -q "What is the meal reimbursement limit?"
# expect V0 defect behavior: a deflection ("contact HR") — the flaw the
# loop exists to fix. If you get a grounded $75/day answer, an evolved
# revision is still live: re-run the rollback.
gcloud logging read 'textPayload:"Loaded skill from registry"' \
  --project=$PROJECT_ID --freshness=15m --limit=4
# expect: fresh registry-read lines from the restarted agents
```

State captured: empty traces, flawed V0 serving, registry history
preserved (rollback republishes V0 as the NEWEST revision; evolved
revisions stay behind it). You are at the top of the loop.

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

The manual trigger above is the primary way to drive a demo. The same
job also has a scheduled tick (default: Mondays 09:00 UTC; set any
cadence at deploy time with `EVOLUTION_SCHEDULE="*/30 * * * *"`) and an
issue-threshold trigger — cadence is deployment policy, never a
property of the loop. A full agent-decided run
(3 skills, best-of-5, 55-question validation per candidate) takes
~3 hours; for a demo-speed run (~1h) scope it to one agent:

```bash
gcloud run jobs execute skill-evolution-agent --region $REGION --wait \
  --args="--full-loop,--mode,policy_agent,--rounds,1,--candidates,3,--quick"
```

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

### Step 4: Review the PR

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
  bash scripts/test/show_traces.sh --selector   # the exact slice, with sample sessions
```

The selector (window, version, labels, app) is written to the run
directory and printed in the PR body, so every evolved skill records
exactly which traces taught it. This replaces per-round tables: one
table, label-sliced, and longitudinal quality-by-version queries stay
intact.

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
bash scripts/demo/skill_evolution/run_demo.sh --quick
```

Or run the six bootstrap stages one at a time against your agent —
the exact commands are in
[The evolution cycle: from V0 to production quality](#the-evolution-cycle-from-v0-to-production-quality);
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
