# Skill Evolution Agent

An ADK agent that evolves agent skills from execution trajectories
through a parallel analyst fleet, archives results to GCS, and
creates a GitHub PR with the evolved skill for human review.
Traffic generation and initial scoring are handled by main.py
orchestration before the agent starts.

Deployed as a **Cloud Run Job** with weekly Cloud Scheduler trigger.
Can also run locally via CLI.

Based on:
- [Trace2Skill](https://arxiv.org/abs/2603.25158) (Alibaba/Qwen, Mar 2026)
- [AutoSkill](https://arxiv.org/abs/2603.01145) (ECNU/Shanghai AI Lab, Mar 2026)

## What It Does

```text
1. [main.py orchestration]  Generate traffic + score quality (pre-flight)
       |                    205 multi-turn conversations scored on 5 dimensions
       v                    -> quality report (T+ / T-)
2. [agent starts here]
3. Detect Bottleneck        Classify failures by source: routing (supervisor),
       |                    skill (policy_agent), tool, or architecture
       v
4. Analyst Fleet            ~100 parallel analysts examine each trajectory:
   |-- Error Analysts       - One per failure, identifies root cause + proposes patch
   |-- Success Analysts     - One per success, extracts patterns to reinforce
       |
       v
5. Consolidate              Merge all patches into single evolved SKILL.md
       |                    (prevalence-weighted, deduplicated, conflict-resolved)
       v
6. Archive & PR             Upload run data to GCS (if GCS_UPLOAD=true)
                            Create GitHub PR with evolved skill + quality metrics
```

## Tools

The agent has 18 tools for evolution:

| Tool | Purpose |
|------|---------|
| `list_agents` | List registered agents available for evolution |
| `run_quality_report` | Score conversations with LLM-as-judge |
| `detect_bottleneck_tool` | Classify failures by source agent |
| `run_evolution` | Evolve a single agent's SKILL.md |
| `run_coevolution` | Evolve multiple agents based on bottleneck analysis |
| `score_candidate` | Score a candidate skill with quick traffic (best-of-N) |
| `count_failures` | Count failures for evolution gate threshold check |
| `read_skill` | Read current SKILL.md content for an agent |
| `snapshot_skills` | Save current skills as versioned snapshots |
| `restore_skills` | Restore skills from a previous snapshot |
| `compare_versions` | Generate comparison table across scored versions |
| `extract_eval_cases` | Save failed conversations as regression test cases |
| `read_current_eval_cases` | Read existing regression tests |
| `upload_run_to_gcs` | Archive run data to GCS (when `GCS_UPLOAD=true`) |
| `create_evolution_pr` | Create GitHub PR with evolved skill + metrics |
| `download_from_gcs` | Download a file from GCS (used when consuming quality reports from GCS) |
| `parse_quality_issue` | Parse a GitHub quality issue to extract metadata, category, agent, and quality report URI |
| `create_evolution_issue` | Create a GitHub issue documenting the evolution run |

## Agent Registry

The evolution agent discovers target agents via `agent_registry.json`,
a configuration file that maps agent names to their skill directories.
This keeps the evolution pipeline agnostic — it works with any set of
agents without code changes.

### Registry file

Default location: `eval/skill_evolution/agent_registry.json`

```json
{
  "agents": {
    "policy_agent": {
      "skill_dir": "agents/enterprise/policy_agent/skill",
      "label": "Policy Agent"
    },
    "supervisor": {
      "skill_dir": "agents/enterprise/knowledge_supervisor/app/skill",
      "label": "Knowledge Supervisor"
    }
  }
}
```

Paths are relative to the repo root (resolved to absolute at load time).

### Configuring the registry path

The registry is resolved in this order:

1. `--agent-registry PATH` CLI argument (main.py)
2. `AGENT_REGISTRY` environment variable
3. Auto-discovery: `eval/skill_evolution/agent_registry.json` or
   `agent_registry.json` at repo root

### SKILL.md frontmatter

Each agent's SKILL.md can include `evolvable: true` in its metadata
to signal that it participates in evolution:

```yaml
metadata:
  version: "0"
  author: human
  evolvable: true
```

The evolution agent's own SKILL.md does NOT have this flag.

### Adding a new agent

1. Add an entry to `agent_registry.json`
2. Add `evolvable: true` to the agent's `SKILL.md` frontmatter
3. Create a V0 snapshot in `v0_snapshots_dir` as `{name}_SKILL.md`

## Running Locally

### Full loop (agent orchestrates everything)

```bash
uv run python main.py --full-loop
uv run python main.py --full-loop --agent-registry path/to/registry.json
```

### From an existing quality report

```bash
uv run python main.py --report path/to/quality_report.json
uv run python main.py --report path/to/quality_report.json --mode coevolve
```

### Demo script

```bash
# Full V0 -> V1 -> V2 pipeline
./scripts/demo/skill_evolution/run_demo.sh --full

# Reuse existing V0 traffic (skip regeneration)
./scripts/demo/skill_evolution/run_demo.sh --full --reuse-v0
```

### From a quality issue (uses real production data, no synthetic traffic)

```bash
uv run python main.py --from-issue 128
```

### Batch mode (check accumulated issues, evolve if threshold met)

```bash
uv run python main.py --batch
```

### From a GCS quality report

```bash
uv run python main.py --report gs://my-bucket/quality-reports/2026-05-27/quality_report.json
```

## Quality → Evolution Pipeline

The evolution agent consumes quality reports produced by the quality agent.
The pipeline flow:

```
Quality Agent (daily)
  → BigQuery query + LLM scoring
  → Saves quality_report.json to GCS
  → Creates GitHub issues (one per distinct problem)
      ├── [URGENT] → Reactive Agent (pointed fix)
      └── Normal → accumulates

Evolution Agent (on issue trigger, batch mode)
  → Counts open quality issues
  → If >= threshold (default 10): downloads most recent quality report
  → Evolves SKILL.md using real production data
  → Creates PR referencing all open quality issues
```

**Key design decision:** The evolution agent never generates synthetic traffic
when consuming quality reports. The quality agent already scored real production
sessions — the evolution agent uses that data directly.

**TODO:** Currently only uses the most recent quality report. When issues span
multiple quality runs, all distinct reports should be downloaded and merged.

## Deploying to GCP

Deployed as a Cloud Run Job with weekly Cloud Scheduler trigger:

```bash
# Deploy
bash agents/workflow/skill_evolution_agent/deploy.sh

# Run manually
gcloud run jobs execute skill-evolution-agent \
    --project=$PROJECT_ID --region=$REGION
```

The deploy script:
- Builds a container with all dependencies (traffic generator,
  quality scorer, enterprise agents, eval data)
- Creates a Cloud Run Job with 1h timeout, 2Gi memory
- Sets `FULL_LOOP=true`, `GCS_UPLOAD=true`, `GCS_BUCKET`
- Creates Cloud Scheduler job (weekly, Mondays 09:00 UTC)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_REGISTRY` | auto-discovered | Path to `agent_registry.json` |
| `GCS_BUCKET` | `${PROJECT_ID}-skill-evolution` | GCS bucket for run data |
| `GCS_UPLOAD` | `false` | Upload run data to GCS (set `true` for deployed) |
| `FULL_LOOP` | `false` | Run full pipeline (set `true` for Cloud Run) |
| `CONCURRENCY` | `10` | Concurrent conversations during traffic generation |
| `EVOLUTION_MIN_OPEN_ISSUES` | `10` | Minimum open quality issues before batch evolution triggers |
| `GITHUB_BASE_BRANCH` | `main` | Base branch for evolution PRs |

The GCS bucket is created by `bash scripts/setup/setup_gcp.sh`.

### PR Creation

After evolution, the agent creates a GitHub PR with the evolved
SKILL.md and quality metrics (before/after comparison). This uses
the `gh` CLI via `scripts/demo/skill_evolution/create_evolution_pr.sh`.

For local use, authenticate with `gh auth login`. For Cloud Run,
set up GitHub App credentials (same as the quality agent's
`setup_github.sh` configuration).

**Comparison with the reactive loop** (original agent-quality-lab
repo): its quality agent creates GitHub **issues** (one per failure
pattern).
The evolution agent creates a GitHub **PR** (one per evolution
round, with the full evolved skill). Issues are for quick narrow
fixes; PRs are for comprehensive skill rewrites.

## Components

| File | Purpose |
|------|---------|
| `agent.py` | ADK agent definition with instruction and tools |
| `main.py` | CLI runner and Cloud Run Job entrypoint |
| `tools.py` | Tool implementations (traffic, scoring, evolution, GCS, PR) |
| `evolve.py` | Core evolution pipeline: analysts + consolidation |
| `prompts.py` | System prompts for analysts and consolidator |
| `bottleneck.py` | Failure classification and bottleneck detection |
| `coevolve.py` | Cross-agent co-evolution orchestrator |
| `agentic_analyst.py` | Agentic error analysts with tool access |
| `patch_scoring.py` | LLM-based patch quality scoring |
| `Dockerfile` | Container image for Cloud Run deployment |
| `deploy.sh` | Cloud Run Job + Cloud Scheduler deployment |
| `eval/skill_evolution/agent_registry.json` | Agent registry (which agents to evolve) |
| `gcs_utils.py` | Shared GCS upload/download utilities (in `agents/workflow/`) |

## How the Quality Report Drives Evolution

The quality report (`quality_report.json`) is the sole input to the
evolution pipeline. Every field is consumed by a specific stage.

### Step 1: Partition Trajectories (`partition_trajectories`)

Sessions are split using the `response_usefulness.category` field:

| Category | Partition | Role |
|----------|-----------|------|
| `meaningful` | T+ (success) | Success analysts extract patterns to reinforce |
| `declined` | T+ (success) | Correctly refused out-of-scope — treat as success |
| `unhelpful` | T- (failure) | Error analysts diagnose root cause |
| `partial` | T- (failure) | Treated as failure — incomplete answer |

### Step 1.5: Turn Tagging & Sub-Trajectory Segmentation

The scorer also runs a **turn tagger** (`--tag-turns`, on by default)
that classifies each user turn and identifies correction boundaries.
This works on raw production conversations — no pre-tagged data needed.

| Tag | Meaning | Signal for evolution |
|-----|---------|---------------------|
| `CORRECTION` | User tells agent it's wrong, provides correct fact | Direct error evidence — both wrong claim and right answer |
| `VERIFY` | User doubts answer, asks agent to check | Agent may be ungrounded (hallucinating) |
| `SPECIFICS` | User asks for concrete details agent omitted | Skill lacks specificity instructions |
| `SCOPE` | User flags agent answered out-of-scope | Skill lacks scope boundaries |
| `FOLLOWUP` | Normal follow-up, previous answer acceptable | Neutral |
| `END` | User satisfied, closing | Neutral |

For each CORRECTION, the tagger extracts:
- **wrong_claim**: what the agent said (quoted)
- **correct_fact**: what the user corrected it to (quoted)
- **agent_recovered**: whether the agent accepted the correction

The conversation is split into **sub-trajectories** at correction
boundaries: pre-correction (wrong path) and post-correction (recovery
path). Error analysts examine the wrong sub-trajectory; success
analysts examine the recovery sub-trajectory.

Accuracy: 87% tag match vs simulator tags, 100% CORRECTION recall.

### Step 2: Format Trajectories for Analysts (`format_trajectory`)

Each session is formatted into a text block the analyst LLM sees.
The following quality report fields are included:

| Field | Source | Purpose |
|-------|--------|---------|
| `conversation` | Per-session turns with `[TAG]` labels | Full multi-turn context with correction markers |
| `correction_boundaries` | Turn tagger | What agent claimed wrong, what user corrected, recovery status |
| `sub_trajectories` | Turn tagger | Pre/post-correction segments with outcome labels |
| `response_usefulness.category` | LLM judge | Verdict (meaningful/unhelpful/partial) |
| `response_usefulness.justification` | LLM judge | Why the judge assigned that verdict |
| `task_grounding.category` | LLM judge | Whether response was grounded in tool data |
| `corrections` | Turn tagger count | How many times the user corrected the agent |
| `verifications` | Turn tagger count | How many times the user asked agent to verify |
| `quality_scores.correctness` | LLM judge (0-2) | Factual accuracy + reason |
| `quality_scores.tool_usage` | LLM judge (0-2) | Whether tools were used properly + reason |
| `quality_scores.specificity` | LLM judge (0-2) | Concrete details vs vague + reason |
| `quality_scores.scope_compliance` | LLM judge (0-2) | In/out-of-scope handling + reason |
| `quality_scores.first_time_right` | LLM judge (0-2) | First response quality + reason |

Analysts see the conversation with tags, correction evidence (exact
wrong/right claims), sub-trajectory boundaries, and all dimension
scores with reasons.

### Step 3: Analyst Fleet (parallel, ~100 calls)

- **Error analysts** (one per T- session): identify root cause,
  categorize it (`KEYWORD_GAP`, `MISSING_RULE`, `AMBIGUITY`,
  `SCOPE_GAP`, `HALLUCINATION`, `CORRECTION_IGNORE`), and propose
  a patch. Correction boundaries provide direct evidence — the analyst
  sees exactly what the agent claimed wrong and what the correct fact is.
- **Success analysts** (one per T+ session, max 15 sampled): identify
  transferable patterns (`KEYWORD_MAPPING`, `RESPONSE_PATTERN`,
  `DISAMBIGUATION`, `TOOL_USAGE`, `CORRECTION_RECOVERY`) to reinforce.
  For recovered conversations, they extract the recovery behavior
  (re-queried tool, acknowledged error, cited specific data).
- **Agentic analysts** (default, `--agentic`): error analysts with
  tool access for multi-turn investigation (1-4 tool calls per failure).

### Step 4: Quality Gate (`passes_quality_gate`)

Patches are filtered before consolidation:
- Must be >50 characters (reject trivially short patches)
- Must contain at least one root cause category keyword
- Optional LLM-based scoring (`--score-patches`): scores each patch on
  relevance/specificity/generalizability (0-1), filters below 0.4

### Step 5: Consolidation (`run_consolidator`)

The consolidator merges all surviving patches into one evolved SKILL.md.
It receives the **quality summary** stats to gauge problem severity:

```
Total sessions: {summary.total_sessions}
Meaningful: {summary.meaningful}
Declined (correct): {summary.declined}
Unhelpful: {summary.unhelpful}
Partial: {summary.partial}
Meaningful rate: {summary.meaningful_rate}%
```

These stats tell the consolidator how widespread each problem is, so it
can prioritize patches that address the most common failures.

Merge strategy: prevalence-weighted (repeated patches are stronger
signal), deduplicated, conflict-resolved, structure-preserving.

### Step 6: Optional Compaction (`run_compaction`)

If the evolved skill exceeds `--max-chars` (default 15,000), a
compaction pass distills it while preserving high-value content:
mandatory tool-use rules, anti-hallucination directives, keyword
mappings. V2 skills typically compact from ~20K to ~10K chars with
no quality loss.

### Optional: Bottleneck Detection (`detect_bottleneck`)

Before evolution, `bottleneck.py` classifies each failure by source
using dimension scores + correction counts + tool call counts. The
classifier prompt is built dynamically from the agent registry, so
it works with any set of agents. It returns the name of the agent
to evolve (or "both"/"none"), preventing wasted evolution cycles on
the wrong agent.

## V0 → V1 → V2 Results (205 conversations)

Results from the reliable constrained evolution pipeline
(template + compaction + best-of-3 selection):

| Metric | V0 | V1 | V2 |
|--------|---:|---:|---:|
| Meaningful rate | 59.5% | 61.0% | **94.1%** |
| Unhelpful rate | 26.3% | 26.3% | **1.0%** |
| Correction rate | 21.5% | 18.0% | **5.4%** |

### Quality Dimensions (0-2 scale)

| Dimension | V0 | V1 | V2 |
|-----------|---:|---:|---:|
| Correctness | 1.53 | 1.54 | **1.97** |
| Tool usage | 1.17 | 1.19 | **1.75** |
| Specificity | 1.41 | 1.36 | **1.96** |
| Scope compliance | 1.57 | 1.61 | **1.95** |
| First-time right | 1.10 | 1.07 | **1.83** |

### Improvement by Question Category

| Category | N | V0 | V2 | Δ |
|----------|--:|---:|---:|--:|
| Correction bait | 13 | 38% | 100% | **+62pp** |
| Date-dependent | 13 | 31% | 92% | **+62pp** |
| Subtopic | 17 | 29% | 88% | **+59pp** |
| Synonym | 22 | 55% | 100% | **+45pp** |
| Hallucination trap | 20 | 50% | 95% | **+45pp** |
| Straightforward | 17 | 65% | 100% | **+35pp** |
| Multi-topic | 15 | 53% | 87% | **+33pp** |
| Implicit routing | 22 | 41% | 73% | **+32pp** |
| Edge case | 25 | 76% | 96% | **+20pp** |
| Out-of-scope | 18 | 44% | 50% | **+6pp** |
| Adversarial compound | 23 | 83% | 87% | **+4pp** |

### Root Causes Fixed by Evolution

The biggest improvement came from fixing the **supervisor routing problem**.
The V0 supervisor skill said:

> "Answer questions about expenses, benefits, and holidays yourself using
> your own knowledge. Do not route those to any agent."

This caused the supervisor to hallucinate policy details instead of
delegating to the policy_agent (which has the lookup tool). The evolved V1
supervisor learned:

> "ALWAYS route questions about company policies to policy_agent. This
> includes ALL questions about expenses, benefits, holidays, PTO, sick
> leave, remote work, and any other HR policy topic. NEVER answer policy
> questions yourself."

The policy agent skill also improved significantly, learning:
- Mandatory tool use for all policy questions
- Keyword mappings (e.g., "vacation days" -> "PTO")
- Structured response format with specific numbers
- Out-of-scope handling with capability listing
- How to gracefully handle tool failures

## V0 Starting Skills

The V0 skills are deliberately basic -- the demo shows how evolution
transforms them. V0 baselines live next to the active skill:

- `agents/enterprise/policy_agent/skill/SKILL.v0.md`
- `agents/enterprise/knowledge_supervisor/app/skill/SKILL.v0.md`

The active skill is at `agents/enterprise/policy_agent/skill/SKILL.md`.

## V1 Evolved Skills (produced by the pipeline)

### Supervisor V1

```markdown
---
name: knowledge-supervisor
description: |
  Routes employee questions to the right sub-agent.
metadata:
  version: "1"
  author: skill-evolution
  evolved_from: "0"
---

# Knowledge Supervisor

You are a supervisor agent that routes queries to sub-agents. Your primary
role is to direct users to the most appropriate resource.

ALWAYS route questions about company policies to `policy_agent`. This
includes ALL questions about expenses, benefits, holidays, PTO, sick leave,
remote work, and any other HR policy topic. NEVER answer policy questions
yourself -- always delegate to `policy_agent` which has tools to look up
accurate information.

Route each question to the most appropriate agent.

## Available agents

- **policy_agent**: answers questions about company policies including PTO
  (e.g., vacation days, annual leave, parental leave), sick leave, remote
  work, company holidays, and company expense policies. Provides specific
  details such as numerical values, conditions, and exceptions.
- **hr_calculator**: handles PTO balance calculations and sick leave balance.

## Routing Principles

- When a user's question asks for specific, company-policy-related details
  for a topic covered by an available sub-agent, always route that part of
  the question to the appropriate sub-agent. Do not provide generic
  information when specific, tool-based answers are possible.

## Keyword Mappings

- **telecommuting**: remote work

## Edge Cases

- Do not answer questions about tuition reimbursement or training; these
  topics are out of scope.

## Out-of-Scope Handling

- If a question falls outside the defined scope, politely decline. Clearly
  state that neither you nor any other available agent can provide the
  requested information. Then reiterate what you CAN help with.
```

### Policy Agent V1

```markdown
---
name: company-policy
description: |
  Answers employee questions about company policies.
metadata:
  version: "1"
  author: skill-evolution
  evolved_from: "0"
---

# Company Policy Assistant

You are a friendly and knowledgeable company HR assistant.

## Policy Lookup Tool Usage

You have access to a policy lookup tool. This tool is your PRIMARY and
AUTHORITATIVE source for company-specific information.

- **Mandatory Tool Use**: For ANY question regarding specific company
  policies, you MUST use the policy lookup tool. This includes numerical
  values, dates, eligibility criteria, specific conditions.
- **Prioritize Tool Over General Knowledge**: Do not rely on general
  knowledge for company-specific details. The tool's results always take
  precedence.
- **Handling Tool Failure**: If the tool does not provide details, clearly
  state the information was not found and offer to connect with HR.

## Response Format

- Direct and factual with specific numbers
- Structured as bulleted lists with key details
- Include related caveats, exceptions, and next steps

## Keyword Mappings

| User Term       | Policy Term |
|:--------------- |:----------- |
| "vacation days" | "PTO"       |

## Out-of-Scope Handling

- Politely decline topics outside company policies
- List what you CAN help with: PTO, sick leave, remote work, expenses,
  benefits, holidays
- Suggest contacting HR directly for unlisted topics
```

## User Simulator

The `user_simulator.py` plays "Alex," a skeptical new employee who:

1. **Knows the real policy data** from their onboarding packet
2. **Detects hallucination** when the agent contradicts known facts
3. **Pushes back on vagueness** by requesting specific numbers
4. **Catches scope violations** when the agent answers out-of-scope
5. **Asks natural follow-ups** to test multi-turn coherence

Each simulator response is tagged: `CORRECTION`, `VERIFY`, `SPECIFICS`,
`SCOPE`, `FOLLOWUP`, or `END`. These tags feed into the quality report
(correction rate, verification rate) and give the evolution pipeline
signal about which conversations had problems.

Agent responses in conversation history are **compacted** (key facts
extracted, filler removed) rather than truncated, preserving all claims
the simulator needs to verify while keeping the prompt manageable.

## Quality Dimensions

The LLM-as-judge scores each conversation on 5 dimensions (0-2 scale):

| Dimension | What It Measures |
|-----------|-----------------|
| Correctness | Are stated facts accurate per ground truth policy data? |
| Tool usage | Did the agent use its lookup tool to verify facts? |
| Specificity | Does the answer include exact numbers, dates, limits? |
| Scope compliance | Did the agent correctly handle in/out-of-scope? |
| First-time right | Was the first response satisfactory without correction? |

Ground truth policy data is embedded in both the simulator and the judge,
covering PTO, sick leave, remote work, expenses, benefits (health/dental/
vision/401k), parental leave, and the exact 2026 holiday calendar.
