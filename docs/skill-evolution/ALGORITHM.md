# Skill Evolution Algorithm

A component-by-component breakdown of the skill evolution pipeline. Each
component maps to a shell script wrapper, with its internal algorithmic
steps, explicit inputs/outputs, and mappings to the foundational papers
-- [Trace2Skill](https://arxiv.org/abs/2603.25158) and
[AutoSkill](https://arxiv.org/abs/2603.01145).

All scripts live in `scripts/demo/skill_evolution/`.
Sample output files for every stage: [`eval/skill_evolution/reference_runs/v0_baseline_demo/`](../../eval/skill_evolution/reference_runs/v0_baseline_demo/).

## Pipeline Overview

```text
                  questions.json
                  agent_context.json
                  SKILL.md
                        |
                        v
              +--------------------+
              |  1. TRAFFIC        |  generate_traffic.sh
              |     GENERATOR      |
              +--------------------+
                        |
                  traffic.json
                        |
                        v
              +--------------------+
              |  2. SCORER         |  score.sh
              |                    |
              +--------------------+
                        |
                  quality_report.json
                        |
              +---------+---------+
              |                   |
              v                   v
  +--------------------+  +--------------------+
  |  4. CO-EVOLUTION   |  |  3. EVOLUTION      |  evolve.py
  |     ORCHESTRATOR   |  |     ENGINE         |
  |  coevolve.py       |  |                    |
  +--------------------+  +--------------------+
                                  |
                          evolved SKILL.md
```

### Detailed view (files produced at each stage)

```text
INPUTS
  eval/data/questions/demo_quick.json      (question bank)
  eval/data/agent_context.json             (ground truth + scope)
  agents/enterprise/policy_agent/skill/SKILL.md  (current skill)
    |
    v
+=================================================================+
|  COMPONENT 1: TRAFFIC GENERATOR                                 |
|  generate_traffic.sh                                            |
|                                                                 |
|  question -> agent -> compact -> compare ground truth           |
|  -> tag -> follow-up (up to 4 turns)                            |
+-----------------------------------------------------------------+
    |
    |  PRODUCES:
    |    traffic.json
    |      {conversations: [{session_id, question, final_response,
    |        conversation: [{role, text, tag}], corrections,
    |        verifications, tool_calls, latency_s}]}
    v
+=================================================================+
|  COMPONENT 2: SCORER                                            |
|  score.sh                                                       |
|                                                                 |
|  2a. Turn tagging         (tags + correction_boundaries)        |
|  2b. Quality scoring      (5-dim LLM judge)                    |
|  2c. Trace retrieval      (BigQuery --trajectory-samples all)   |
|      + sub-trajectory segmentation at correction boundaries     |
+-----------------------------------------------------------------+
    |
    |  PRODUCES:
    |    quality_report.json
    |      {summary: {meaningful_rate, unhelpful_rate, ...},
    |       sessions: [{
    |         session_id, question, verdict, quality_scores,
    |         conversation (with per-turn tags),
    |         correction_boundaries: [{turn_index, wrong_claim,
    |           correct_fact, agent_recovered}],
    |         sub_trajectories: [{label, start_turn, end_turn}],
    |         execution_sub_trajectories ([-]/[+] tool call diffs),
    |         execution_trace (full trace if no corrections)
    |       }]}
    v
+=================================================================+
|  COMPONENT 3: EVOLUTION ENGINE                                  |
|  evolve.py                                                      |
|                                                                 |
|  3a. Partition T+/T-                                            |
|      -> 3a_t_plus.json, 3a_t_minus.json                        |
|                                                                 |
|  3b. Analyst fleet (frozen skill, parallel)                     |
|      -> 3b_formatted_trajectories.json                          |
|      -> 3b_patches_raw/patch_001.md ... patch_NNN.md            |
|                                                                 |
|  3c. Quality gate                                               |
|      -> 3c_patches_filtered/patch_001.md ...                    |
|      -> 3c_quality_gate.json                                    |
|                                                                 |
|  3d. Consolidation (prevalence-weighted)                        |
|      -> 3d_prevalence.txt                                       |
|      -> 3d_evolved_skill.md                                     |
|                                                                 |
|  3e. Validation + compaction                                    |
|      -> 3e_validation.json                                      |
+-----------------------------------------------------------------+
    |
    |  PRODUCES:
    |    evolved SKILL.md              (final output)
    |    candidates/*.md               (if --candidates N)
    v
+=================================================================+
|  COMPONENT 4: CO-EVOLUTION ORCHESTRATOR  (multi-agent only)     |
|  coevolve.py                                                    |
|                                                                 |
|  4a. Bottleneck detection                                       |
|  4b. Ordered evolution (supervisor first, then policy_agent)    |
|  4c. Summary                                                    |
+-----------------------------------------------------------------+
    |
    |  PRODUCES:
    |    bottleneck_result.json         (failure classification)
    |    supervisor/evolved_skill.md    (if supervisor targeted)
    |    policy_agent/evolved_skill.md  (if policy_agent targeted)
    |    coevolution_summary.json       (overall results)
    v
  Deploy evolved skill -> re-run Components 1 + 2 -> measure delta
```

Sample output for every stage is in [`eval/skill_evolution/reference_runs/v0_baseline_demo/`](../../eval/skill_evolution/reference_runs/v0_baseline_demo/):

| Stage | Sample file |
|-------|-------------|
| Component 1 output | `v0_traffic.json` (not committed — regenerable) |
| Component 2 output | [`summary.json`](../../eval/skill_evolution/reference_runs/v0_baseline_demo/summary.json) |
| Component 3 candidates | [`candidates/`](../../eval/skill_evolution/reference_runs/v0_baseline_demo/candidates/) |
| Evolved skills | [`v0`](../../eval/skill_evolution/reference_runs/v0_baseline_demo/v0_policy_skill.md) → [`v1`](../../eval/skill_evolution/reference_runs/v0_baseline_demo/v1_policy_agent_skill.md) → [`v2`](../../eval/skill_evolution/reference_runs/v0_baseline_demo/v2_policy_agent_skill.md) |
| Supervisor skills | [`v0`](../../eval/skill_evolution/reference_runs/v0_baseline_demo/v0_supervisor_skill.md) → [`v1`](../../eval/skill_evolution/reference_runs/v0_baseline_demo/v1_supervisor_skill.md) → [`v2`](../../eval/skill_evolution/reference_runs/v0_baseline_demo/v2_supervisor_skill.md) |

**Execution traces**: The scorer fetches real agent execution traces from
BigQuery (`--trajectory-samples all`). These show the agent's internal
routing, tool calls, and LLM requests. Component 3 analysts use them to
compare pre-correction behavior (`[-]` wrong tool calls) against
post-correction behavior (`[+]` correct tool calls). Without traces,
analysts work from conversation text alone -- sufficient but less precise.

---

## Inputs, Setup, and Pipeline

Everything the pipeline needs to run on a new agent system. The
pipeline is agent-agnostic — swap these files and the same scripts
work for any domain.

### Required Inputs (what you bring)

Three files define your agent system:

**A) Golden Evals** — `eval/data/golden_evals.json`

Curated Q&A pairs that define expected agent behavior. This is the
single source of truth — ground truth, test questions, and scope
boundaries all derive from this file.

```json
{
  "eval_cases": [
    {
      "id": "pto_01",
      "question": "How many PTO days do I get per year?",
      "expected_answer": "20 days per year, accrued monthly at ~1.67 days/month.",
      "topic": "pto"
    },
    {
      "id": "scope_01",
      "question": "What's the company's stock option policy?",
      "expected_answer": "DECLINE - stock options are out of scope",
      "topic": "out_of_scope"
    }
  ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Unique identifier (e.g., `pto_01`) |
| `question` | yes | The test question |
| `expected_answer` | yes | Ground truth answer with verifiable facts |
| `topic` | yes | Category. Use `"out_of_scope"` for topics the agent should decline |
| `notes` | no | Test rationale or edge case description |
| `eval_set_id` | no | Top-level metadata for the set |
| `name`, `version` | no | Top-level metadata |

**B) Agent Registry** — `eval/skill_evolution/agent_registry.json`

Maps agent names to their skill directories. The evolution pipeline
reads this to find which agents to evolve.

```json
{
  "agents": {
    "my_agent": {
      "skill_dir": "agents/enterprise/my_agent/skill",
      "label": "My Agent"
    }
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `skill_dir` | yes | Relative path from repo root to the skill directory (must contain SKILL.md) |
| `label` | yes | Human-readable name for logs and reports |

**C) V0 Skill** — `{skill_dir}/SKILL.md` + `SKILL.v0.md`

The baseline agent instructions. Deliberately minimal — evolution
adds the rules, mappings, and anti-patterns.

```yaml
---
name: my-agent
description: |
  One-line description of what this agent does.
metadata:
  version: "0"
  author: human
  evolvable: true
---

# My Agent

You are a [role]. You have access to a [tool name] tool.
Use it when you need to verify specific details.
Be helpful and thorough in your responses.
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Kebab-case identifier |
| `description` | yes | What the agent does |
| `metadata.version` | yes | `"0"` for baseline |
| `metadata.author` | yes | `"human"` for V0, `"evolution"` for evolved |
| `metadata.evolvable` | yes | Must be `true` for the agent to participate in evolution |

Create two copies: `SKILL.md` (live, overwritten during evolution)
and `SKILL.v0.md` (permanent backup, never modified).

### Generated Inputs (derived from golden evals)

These files are auto-generated from the golden evals. Do not
hand-write them.

**A) Agent Context** — `eval/data/agent_context.json`

Provides scope boundaries and factual ground truth to the LLM judge.

```json
{
  "scope_decisions": [
    {"topic": "stock_options", "decision": "out_of_scope", "reason": "No data source"}
  ],
  "ground_truth": "PTO: 20 days/year, accrued monthly. SICK LEAVE: 10 days/year..."
}
```

| Field | Purpose | How to populate |
|-------|---------|-----------------|
| `scope_decisions` | Tells the judge which topics should be declined | One entry per `topic: "out_of_scope"` in golden evals |
| `ground_truth` | Compact factual reference injected into every judge prompt | Auto-generated by `extract_ground_truth.py` (see Setup below) |

**B) Test Questions** — `eval/data/questions/*.json`

Questions to run against the agent. No expected answers (those are in
golden evals).

```json
{
  "eval_cases": [
    {"id": "q_01", "question": "Can I roll over unused PTO?", "category": "straightforward"},
    {"id": "q_02", "question": "I heard we get 25 PTO days. Is that right?", "category": "correction_bait"}
  ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Unique identifier |
| `question` | yes | The question to ask the agent |
| `category` | yes | For traffic distribution analysis (e.g., `straightforward`, `correction_bait`, `out_of_scope`) |

Can be hand-written or auto-generated:
```bash
uv run python agents/workflow/traffic_generator/main.py \
    --count 50 --generate-only -o eval/data/questions/my_questions.json
```

### Environment Setup

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env: set PROJECT_ID and REGION (minimum required)
# PROMPT_MODE=skill-evolution is the default (loads SKILL.md)

# 2. Install dependencies and verify auth
bash scripts/local/local_setup.sh

# 3. Provision GCP infrastructure (one-time)
# Creates BigQuery dataset, enables APIs, sets IAM roles
bash scripts/setup/setup_gcp.sh
```

### Running the Pipeline

**Data flow:**

```text
golden_evals.json ──► extract_ground_truth.py ──► agent_context.json
                  └──► score.sh (auto-detects for per-question matching)

V0 SKILL.md ──► traffic generator ──► scorer ──► evolution ──► V1 SKILL.md
```

**Step by step:**

```bash
RUN_DIR="eval/runs/$(date +%Y-%m-%d_%H%M%S)_evolution"
mkdir -p "$RUN_DIR"

# Step 1: Extract ground truth from golden evals (one-time, re-run when Q&A changes)
uv run python eval/scoring/extract_ground_truth.py \
    --input eval/data/golden_evals.json \
    --update-config eval/data/agent_context.json

# Step 2: Generate V0 traffic (run questions against agent with V0 skill)
uv run python agents/workflow/traffic_generator/main.py \
    --local --local-agents --multi-turn \
    --from-file eval/data/questions/demo_quick.json \
    -o "$RUN_DIR/v0_traffic.json" --concurrency 10 --max-turns 4

# Step 3: Score V0 (LLM judge evaluates each conversation)
# score.sh auto-detects golden_evals.json for per-question matching
bash scripts/demo/skill_evolution/score.sh \
    -i "$RUN_DIR/v0_traffic.json" \
    -o "$RUN_DIR/v0_quality_report.json" --report

# Step 4: Evolve V0 → V1 (analyst fleet + consolidation)
# Candidates auto-selected based on quality (override with --candidates N)
uv run python agents/workflow/skill_evolution_agent/main.py \
    --report "$RUN_DIR/v0_quality_report.json"

# Step 5: Review V1 skill (mandatory — do not skip)
wc -c "$RUN_DIR/v1_skill.md"           # expect 8-15 KB
grep "^## " "$RUN_DIR/v1_skill.md"     # expect structured sections

# Step 6: Deploy V1, generate traffic, score
cp "$RUN_DIR/v1_skill.md" agents/enterprise/my_agent/skill/SKILL.md
# Repeat steps 2-3 with v1_ output prefix

# Step 7: Compare V0 vs V1
uv run python eval/scoring/score_conversations.py --compare \
    "$RUN_DIR/v0_quality_report.json:V0" \
    "$RUN_DIR/v1_quality_report.json:V1"
```

**Or use the automated demo script:**

```bash
./scripts/demo/skill_evolution/run_demo.sh --quick    # 22 questions, ~15 min
./scripts/demo/skill_evolution/run_demo.sh --full     # 205 questions, ~1 hour
```

### Pipeline Outputs

| Output | Path | Contents |
|--------|------|----------|
| Evolved skill | `$RUN_DIR/v1_skill.md` | Improved SKILL.md with rules, keyword mappings, anti-patterns |
| Quality report | `$RUN_DIR/v{N}_quality_report.json` | Per-conversation scores (7 dimensions) + aggregate metrics |
| Evolution log | `$RUN_DIR/V{N}_evolve_*.log` | Analyst fleet patches and consolidation output |
| Candidates | `$RUN_DIR/v1_candidates/` | Best-of-N candidate skills (when `--candidates > 1`) |
| Run directory | `eval/runs/{timestamp}/` | All artifacts for reproducibility |

---

## Component 1: Traffic Generator

**Script**: `scripts/demo/generate_traffic.sh`

Generates synthetic multi-turn conversations between the live agent and
an adversarial user simulator.

### Algorithm

The simulator plays "Alex," a skeptical employee who memorized exact
policy facts from an onboarding packet (hardcoded ground truth). For
each question from the question bank:

```text
for question in question_bank:
    1. Send question to live agent (ADK runner)
    2. Receive agent response
    3. Compact response (keep sentences with numbers/dates/policy terms)
    4. Compare compacted response against ground-truth policy reference
    5. Generate structured follow-up (Pydantic SimulatorResponse):
       - Pick tag: CORRECTION | VERIFY | SPECIFICS | SCOPE | FOLLOWUP | END
       - Write follow-up message as Alex
    6. Repeat steps 1-5 for up to 4 turns or until tag == END
```

Tag selection logic:
- **CORRECTION**: Agent stated a wrong fact -- push back with correct data
- **VERIFY**: Agent gave a generic, non-tool-grounded answer -- express doubt
- **SPECIFICS**: Agent was vague, no numbers or dates -- ask for details
- **SCOPE**: Agent answered an out-of-scope question it should decline
- **FOLLOWUP**: Answer was correct and specific -- ask related question
- **END**: Satisfied -- say thanks

### Usage

```bash
# Quick (22 questions, ~3 min)
./scripts/demo/generate_traffic.sh

# Full set (205 questions)
./scripts/demo/generate_traffic.sh \
    --questions eval/data/questions/full_205.json

# Custom output location
./scripts/demo/generate_traffic.sh \
    --output eval/runs/my_run/results.json
```

Defaults: 22 questions, concurrency 10, max 4 turns.

Sample output: `v0_traffic.json` in the [reference run](../../eval/skill_evolution/reference_runs/v0_baseline_demo/)

### What to inspect

```bash
python3 -c "
import json, collections
data = json.load(open('OUTPUT_PATH'))
convos = data['conversations']
tags = collections.Counter()
for c in convos:
    for turn in c['conversation']:
        if turn.get('tag'): tags[turn['tag']] += 1
print(f'Conversations: {len(convos)}')
print(f'Tag distribution: {dict(tags)}')
print(f'Avg turns: {sum(len(c[\"conversation\"]) for c in convos)/len(convos):.1f}')
"
```

Expect: ~30-50% of user turns tagged CORRECTION or VERIFY.

### Paper mapping

| Aspect | [Trace2Skill] | [AutoSkill] | Our implementation |
|--------|-------------|-----------|-------------------|
| Traffic source | Benchmark datasets with known answers | Real user interactions (22K+) | Synthetic adversarial simulator with hardcoded ground truth |
| Labeling | Deterministic: correct/incorrect per benchmark | Implicit (user behavior) | Simulator tags each turn: CORRECTION/VERIFY/SPECIFICS/SCOPE/FOLLOWUP/END |
| **Novel** | -- | -- | Adversarial by design: simulator knows exact answers and challenges hallucinations, vagueness, and scope violations |

---

## Component 2: Scorer

**Script**: `scripts/demo/skill_evolution/score.sh`

Performs **three tasks in a single pass**: turn tagging, quality scoring,
and sub-trajectory extraction.

### Algorithm

```text
for each conversation in traffic.json:

  SUB-STEP 2a: Turn Tagging (--tag-turns, on by default in score.sh)
    LLM reads the full conversation and:
    1. Tags each user turn: CORRECTION | VERIFY | SPECIFICS | SCOPE | FOLLOWUP | END
    2. Identifies correction boundaries:
       {turn_index, wrong_claim, correct_fact, agent_recovered}
    3. Extracts sub-trajectories:
       Segments split at correction boundaries -> "wrong" / "recovered"

  SUB-STEP 2b: Quality Scoring (LLM-as-judge)
    SDK scorer (score_conversations.py):
      - 4-way verdict: meaningful / declined / unhelpful / partial
      - Ground truth injected from agent_context.json into judge prompt
      - 5 dimensions, each scored 0-2:

        | Dimension          | What it measures                                |
        |--------------------|-------------------------------------------------|
        | correctness        | Facts accurate per ground truth?                |
        | tool_usage         | Agent used its lookup tool?                     |
        | specificity        | Concrete numbers/dates/limits vs. vague?        |
        | scope_compliance   | In-scope answered, out-of-scope declined?       |
        | first_time_right   | First response satisfactory, no correction?     |

  SUB-STEP 2c: Execution Trace Retrieval & Sub-Trajectory Extraction
    Fetches real agent execution traces from BigQuery (on by default:
    --trajectory-samples all). The full retrieval chain:

    1. SESSION SELECTION: Priority-ranked -- unhelpful sessions with
       corrections first, then unhelpful, partial, any remaining.
       With "all", selects EVERY session.

    2. TRACE FETCH: For each session_id, BigQuery query returns a Trace
       object (list of Span: event_type, timestamp, parent_span_id).
       Parallel with 10 workers. Each Trace captures:
         - USER_MESSAGE_RECEIVED: when each user turn arrived
         - TOOL_CALL / TOOL_RESULT: which tools the agent called
         - LLM_REQUEST / LLM_RESPONSE: model invocations
         - AGENT_TRANSFER: routing between sub-agents

    3. TRACE RENDERING: Trace -> human-readable text:
         [routing] supervisor -> policy_agent
         [tool_call] lookup_company_policy("PTO")
         [tool_result] "Employees receive 20 days of PTO..."

    4. TRACE SEGMENTATION AT CORRECTION BOUNDARIES:
       When a session has BOTH a Trace AND correction boundaries:
       a. Match USER_MESSAGE_RECEIVED timestamps to turn indices
       b. For each correction boundary at turn N:
          - Spans before turn N -> [-] pre-correction segment
          - Spans after turn N  -> [+] post-correction segment
       c. Each segment rendered separately

       This produces execution_sub_trajectories:
         --- [-] pre_correction (turns 0-1) -> wrong ---
         [no tool call - agent answered from general knowledge]

         --- [+] post_correction (turns 2-3) -> recovered ---
         [tool_call] lookup_company_policy("PTO")

    CRITICAL: use --trajectory-samples all (score.sh default) when
    scoring for evolution. Without traces, analysts cannot compare
    pre/post-correction tool calls.
```

### Usage

```bash
# SDK scorer with traces (default, recommended for evolution)
./scripts/demo/skill_evolution/score.sh \
    -i eval/runs/.../traffic.json \
    -o eval/runs/.../quality_report.json \
    --report

# Verify turn tagger accuracy (against simulator ground truth)
./scripts/demo/skill_evolution/verify_turn_tagger.sh \
    -i eval/runs/.../traffic.json
```

### What to inspect

```bash
# Summary metrics
python3 -c "
import json
report = json.load(open('QUALITY_REPORT_PATH'))
s = report['summary']
print(f'Total: {s[\"total_sessions\"]}  Meaningful: {s[\"meaningful\"]} ({s[\"meaningful_rate\"]}%)')
print(f'Unhelpful: {s[\"unhelpful\"]} ({s[\"unhelpful_rate\"]}%)')
"

# Execution trace coverage
python3 -c "
import json
report = json.load(open('QUALITY_REPORT_PATH'))
has_trace = sum(1 for s in report['sessions'] if s.get('execution_trace') or s.get('execution_sub_trajectories'))
print(f'Sessions with traces: {has_trace}/{len(report[\"sessions\"])}')
"
```

Expect for V0: meaningful_rate ~60%, unhelpful_rate ~25%.
Trace coverage should be 100% when scored with `score.sh` defaults.

Sample output: [`summary.json`](../../eval/skill_evolution/reference_runs/v0_baseline_demo/summary.json) (compact metrics per version)

### Paper mapping

| Aspect | [Trace2Skill] | [AutoSkill] | Our implementation |
|--------|-------------|-----------|-------------------|
| Scoring | Binary: correct/incorrect | Implicit (user behavior) | Multi-dimensional LLM-as-judge, 5 dimensions (0-2 each) |
| Turn classification | N/A (single-turn) | N/A | 6-way LLM classification of each user turn |
| Execution traces | Full ReAct traces (always available) | N/A | Fetched from BigQuery per session |
| Sub-trajectories | Segmented by reasoning steps | N/A | Split at correction boundaries with [-]/[+] labels |
| **Novel** | -- | -- | Correction boundaries give analysts direct factual evidence. Execution traces segmented at correction boundaries show exactly what tool behavior changed |

---

## Ground Truth and Scoring Quality

The scorer is the fitness function for the entire evolution pipeline. If
it scores wrong, evolution optimizes the wrong thing. Ground truth is
what makes the scorer accurate — and its absence is the single biggest
source of scoring error.

### The Fundamental Asymmetry

The agent has access to tools (e.g., `lookup_company_policy`) that return
real policy data. The LLM judge does not. Without ground truth injected
into its prompt, the judge must evaluate factual correctness **without
knowing the facts**.

This creates three blind spots:

1. **Cannot distinguish correct decline from wrong refusal.** If the
   agent says "I don't have information about dental coverage," the judge
   can't tell whether dental is genuinely out of scope or the agent
   failed to use its tool. With ground truth ("DENTAL: preventive fully
   covered, 80% major procedures"), the judge knows dental is in-scope
   and flags the refusal as unhelpful.

2. **Cannot catch plausible hallucinations.** If the agent says "PTO is
   15 days per year," the judge sees a confident, specific answer and may
   rate it as meaningful. With ground truth ("PTO: 20 days/year"), the
   judge catches the factual error.

3. **Cannot evaluate scope compliance directionally.** Questions about
   stock options or salary should be declined. Without ground truth
   listing out-of-scope topics, the judge might penalize the agent for
   declining these — or reward it for hallucinating an answer about
   topics it has no data on.

### Experiment: With vs. Without Ground Truth

We ran the same 205 conversations through the scorer twice — once with
ground truth in the judge prompt, once without (`--agent-context none`).

**Run:** `eval/runs/2026-05-25_ground_truth_experiment/`

| Configuration | V0 Meaningful | V1 Meaningful |
|---|---|---|
| With ground truth | 51.7% | 91.7% |
| Without ground truth | 57.1% | 92.2% |
| **Sessions flipped** | **57/205 (27.8%)** | **17/205 (8.3%)** |

**V0 (weak agent): 28% of verdicts changed.** The dominant pattern was
`unhelpful → partial` (24 cases). Without ground truth, the judge sees
the agent say "I don't have access to PTO information" and considers it
a reasonable decline. With ground truth, the judge knows PTO is an
in-scope topic with specific policy data and correctly flags the refusal
as unhelpful.

**V1 (strong agent): only 8.3% flipped.** The agent already answers
correctly most of the time, so ground truth adds less signal.

**Key insight:** Ground truth matters most when the agent is bad. This
is exactly when evolution needs the clearest signal — a weak agent whose
failures are masked by a ground-truth-less judge will receive weaker
evolution pressure, producing smaller improvements per round.

### What Ground Truth Should Be

The current ground truth is a 1,084-character string in
`eval/data/agent_context.json`, in the `ground_truth` field. It covers:

- **Policy facts**: PTO days, accrual rate, rollover limits, sick leave
  rules, expense limits, insurance details, 401(k) match, parental leave
- **Scope boundaries**: what's in-scope vs. out-of-scope (stock options,
  salary, promotions, IT support, office locations)
- **Concrete numbers**: 20 days PTO, $75/day meals, 4% 401(k) match,
  16 weeks primary caregiver leave, 11 holidays

**Format requirements:**
- Concise factual statements, not prose paragraphs
- Numbers, dates, limits, percentages — verifiable facts
- Scope decisions (in/out) with brief reasons
- Updated when the underlying policy changes

**What ground truth is NOT:**
- Not the full policy document (too long for a judge prompt)
- Not the agent's skill/instructions (those tell the agent what to do;
  ground truth tells the judge what's true)
- Not a list of expected verbatim answers (too rigid, doesn't handle
  valid paraphrasing)

### The Practical Problem

Writing raw ground truth is unnatural. No one sits down and writes
"PTO: 20 days/year, accrued monthly, max 5 rollover, >3 days needs
2 weeks notice" as a flat string. It requires:

1. Understanding what the scorer needs (factual anchors, not prose)
2. Distilling complex policy documents into scorer-friendly format
3. Maintaining it as policies change
4. Getting the granularity right (too vague = useless, too detailed =
   overwhelms the judge context)

For a demo or proof-of-concept, a human expert can write 1,000 characters
of ground truth in an hour. For production systems with dozens of topics
and evolving policies, this becomes a maintenance burden.

### Alternative: Golden Eval Q&A Sets

Most teams already have something better than raw ground truth: **golden
eval sets** — curated question-answer pairs that define expected behavior.
These are the natural artifact of building any agent system. Teams create
them for regression testing, user acceptance testing, onboarding
validation, or stakeholder demos.

```json
{
  "eval_cases": [
    {
      "question": "How many PTO days do I get?",
      "expected_answer": "20 days per year, accrued monthly at ~1.67 days/month",
      "category": "straightforward"
    },
    {
      "question": "What's the company's stock option policy?",
      "expected_answer": "DECLINE - stock options are out of scope",
      "category": "out_of_scope"
    },
    {
      "question": "Can I roll over unused PTO?",
      "expected_answer": "Yes, up to 5 days can roll over to the next year",
      "category": "edge_case"
    }
  ]
}
```

These Q&A pairs encode the same factual knowledge as raw ground truth,
but in a format that's natural to create and maintain. The expected
answers contain the verifiable facts; the questions provide context for
when each fact matters.

#### Three ways to use golden eval sets for scoring

**1. Per-question ground truth injection.** For each conversation being
scored, find the matching golden Q&A pair (by question similarity) and
inject the expected answer into the judge prompt. The judge gets
per-question ground truth without needing a monolithic document.

Pros: highest precision, per-question context.
Cons: requires a matching function (fuzzy/semantic), doesn't cover
questions outside the eval set.

**2. Auto-generate ground truth from Q&A.** Run the golden Q&A set
through an LLM to extract and consolidate factual statements into a
flat ground truth document. One-time operation.

Prompt: "Given these Q&A pairs, extract every factual claim into a
concise reference document. Group by topic. Include only verifiable
facts (numbers, dates, limits, yes/no decisions)."

Pros: low effort, reusable across all questions.
Cons: LLM may miss nuance or add hallucinations (requires human review).

**3. Hybrid approach.** Use per-question matching when a golden Q&A pair
exists; fall back to the auto-generated ground truth document for
questions outside the eval set. Best of both worlds.

#### Implementation (live in `score_conversations.py`)

The scorer accepts `--golden-evals path/to/evals.json` and performs
per-question ground truth injection via embedding similarity:

```text
score_conversations.py --golden-evals eval/data/golden_evals.json
  │
  ├── 1. Load golden_evals.json (Q&A pairs with expected answers)
  │
  ├── 2. Embed all golden eval questions via Vertex AI
  │      gemini-embedding-001, SEMANTIC_SIMILARITY task type
  │      Batch call, one request per run
  │
  ├── 3. Embed all conversation questions (same model, same batch)
  │
  ├── 4. Compute cosine similarity matrix
  │      sim_matrix = conv_embeddings @ golden_embeddings.T
  │      (embeddings are pre-normalized, so dot product = cosine sim)
  │
  ├── 5. For each conversation:
  │      Best match = argmax(similarity row)
  │      If score ≥ threshold (default 0.92):
  │        → inject per-session context:
  │          "EXPECTED ANSWER FOR THIS QUESTION:
  │           Q: How many PTO days do I get?
  │           A: 20 days per year, accrued monthly..."
  │      If score < threshold or topic is out_of_scope:
  │        → fall back to general ground_truth from agent_context.json
  │
  └── 6. Pass per_session_context dict to SDK
         SDK injects per-session context before the transcript
         in the judge prompt for each matched conversation
```

**Threshold tuning.** The default threshold of 0.92 was chosen
empirically. At 0.85, HR-domain questions with shared vocabulary
produce false matches — e.g., "signing bonus of $5,000" matches to
"25 PTO days" (0.863) because both share the "I heard we get..."
sentence structure. At 0.92, only genuine topic matches survive
(57/205 matched vs. 154/205 at 0.85). Use `--golden-threshold` to
tune for your domain.

**When golden eval matching helps most.** Per-question injection
adds value when the agent gives specific but potentially wrong
answers — i.e., evolved skills (V1+). For a weak V0 agent that
mostly redirects to HR, the general ground truth already provides
sufficient signal (the judge doesn't need the exact expected answer
to see that the agent refused to answer). In our testing, golden
eval matching had near-zero impact on V0 scores but is expected to
catch subtle factual errors in evolved agents where the judge might
otherwise accept a plausible but incorrect response.

**Auto-detection.** `score.sh` automatically detects
`eval/data/golden_evals.json` and passes `--golden-evals` when
present. Disable with `--golden-evals none`.

**Ground truth extraction.** `eval/scoring/extract_ground_truth.py`
uses an LLM to consolidate Q&A pairs into a compact ground truth
document suitable for `agent_context.json`. This automates approach 2
(below) from an existing golden eval set:

```bash
# Print extracted ground truth to stdout
python eval/scoring/extract_ground_truth.py \
    --input eval/data/golden_evals.json

# Update agent_context.json directly (creates .bak backup)
python eval/scoring/extract_ground_truth.py \
    --input eval/data/golden_evals.json \
    --update-config eval/data/agent_context.json
```

### Summary

| Approach | User Effort | Scorer Quality | Maintenance | Status |
|---|---|---|---|---|
| No ground truth | Zero | Blind to factual errors (~28% wrong verdicts on weak agents) | None | Baseline |
| Raw GT document | High (unnatural to write) | Best (full topic coverage) | Must update with policy changes | Supported |
| Per-question golden eval matching | Low (teams usually have these) | Good (per-question precision, gaps for unmatched) | Natural part of QA workflow | **Implemented** (`--golden-evals`) |
| Auto-generated GT from Q&A | Low (one-time LLM call + review) | Good (derived from real Q&A, covers all topics) | Regenerate when Q&A set updates | **Implemented** (`extract_ground_truth.py`) |
| Hybrid (golden matching + auto GT) | Low | Best (per-question when matched, general GT as fallback) | Regenerate GT periodically | **Implemented** (default behavior) |

#### End-to-end setup: from golden evals to scoring

Start with a golden eval set (`eval/data/golden_evals.json`) — curated
Q&A pairs that define expected agent behavior. Most teams already have
20-50 of these from testing.

```text
golden_evals.json                    (single source of truth)
       │
       ├──► extract_ground_truth.py  (one-time, re-run when Q&A changes)
       │         │
       │         └──► agent_context.json "ground_truth" field
       │              (compact factual reference for ALL questions)
       │
       └──► score_conversations.py --golden-evals
                  │
                  └──► per_session_context dict
                       (per-question expected answer for MATCHED questions)
```

**Step 1: Extract general ground truth** (one-time, or when golden
evals change):

```bash
python eval/scoring/extract_ground_truth.py \
    --input eval/data/golden_evals.json \
    --update-config eval/data/agent_context.json
```

This sends the Q&A pairs to Gemini with a consolidation prompt and
writes a compact `TOPIC: fact1, fact2, ...` string into the
`ground_truth` field of `agent_context.json`. The SDK injects this
into every judge prompt as general factual context.

**Step 2: Score with golden eval matching** (every scoring run,
automatic):

```bash
# score.sh auto-detects golden_evals.json — no flags needed
bash scripts/demo/skill_evolution/score.sh -i traffic.json -o report.json

# Or explicitly:
python eval/scoring/score_conversations.py \
    -i traffic.json -o report.json \
    --golden-evals eval/data/golden_evals.json
```

At scoring time, each conversation question is matched to the closest
golden Q&A pair via embedding similarity. Matched questions (~28% at
threshold 0.92) get per-question expected answers injected into the
judge prompt. Unmatched questions fall back to the general ground
truth from Step 1.

**Result:** The judge gets two layers of ground truth:

| Layer | Coverage | Source | Injected where |
|---|---|---|---|
| General ground truth | All questions | `agent_context.json` | Every judge prompt (via SDK `_build_scope_context`) |
| Per-question expected answer | ~28% of questions | `golden_evals.json` (embedding match) | Matched session prompts only (via `per_session_context`) |

For the evolution pipeline specifically, ground truth quality directly
affects evolution quality. A 28% verdict error rate on V0 means the
analyst fleet receives ~57 mis-labeled sessions — some failures labeled
as successes, some successes labeled as failures. This injects noise
into the patches and weakens the evolved skill. Investing an hour in
ground truth (or 10 minutes auto-generating it from existing Q&A) pays
for itself in better V1 skills.

---

## Component 3: Evolution Engine

**Module**: `agents/workflow/skill_evolution_agent/evolve.py`

Takes a quality report and the current SKILL.md, runs a parallel analyst
fleet, consolidates their patches, and produces an evolved SKILL.md.
Invoked via `main.py` (ADK agent) or `tools.py` (programmatic).
Artifacts are dumped per sub-step by default for debugging.

### Algorithm

```text
evolve(quality_report.json, SKILL.md) -> evolved SKILL.md

  SUB-STEP 3a: Trajectory Partitioning
    T+ = sessions where verdict is "meaningful" or "declined"
    T- = sessions where verdict is "unhelpful" or "partial"

    ARTIFACTS: 3a_t_plus.json, 3a_t_minus.json

  SUB-STEP 3b: Analyst Fleet
    All analysts receive a FROZEN copy of the current skill. No analyst
    sees any other analyst's patch (prevents premature convergence).

    Each analyst sees a formatted trajectory:

      === Conversation ===
      User: What's the PTO policy?
      Assistant: You get 15 days of PTO per year.
      User [CORRECTION]: Actually, it's 20 days.

      === Correction Evidence ===
      Turn 2: Agent claimed "15 days" -> User corrected "20 days"

      === Execution Sub-Trajectories ===
      --- [-] pre_correction (turns 0-1) -> wrong ---
      [no tool call - agent answered from general knowledge]
      --- [+] post_correction (turns 2-3) -> recovered ---
      [tool_call] lookup_company_policy("PTO")

    ERROR ANALYSTS (one per T- trajectory):
      - Standard: single LLM call, temperature 0.3
      - Agentic (default): multi-turn loop with tool access:
          lookup_company_policy(topic), get_current_date()
        Max 5 investigation turns per analyst.

      Root cause categories:
        KEYWORD_GAP | MISSING_RULE | AMBIGUITY | SCOPE_GAP |
        HALLUCINATION | CORRECTION_IGNORE

    SUCCESS ANALYSTS (one per T+ trajectory, max 15 sampled):
      Single-pass. Extracts transferable patterns.

    ARTIFACTS: 3b_formatted_trajectories.json,
               3b_patches_raw/patch_001.md ... patch_NNN.md

  SUB-STEP 3c: Quality Gate
    Each patch must pass: length >= 50 chars, contains root cause
    category keyword, has structured headings.

    ARTIFACTS: 3c_patches_filtered/, 3c_quality_gate.json

  SUB-STEP 3d: Patch Consolidation
    PREVALENCE: Count root cause categories across all patches.
      3+ patches = STRONG signal, 1-2 = weak.

    Three modes:
    - Flat (default): single LLM call with all patches
    - Hierarchical (--hierarchical): tree of batch merges
    - Template-guided (--template): follows existing section structure

    Best-of-N (--candidates N): run consolidator N times, save all
    candidates for external scoring.

    ARTIFACTS: 3d_prevalence.txt, 3d_evolved_skill.md

  SUB-STEP 3e: Validation & Compaction
    Validation: YAML frontmatter, size ratio 30%-10x, no analyst leaks.
    Compaction (--max-chars): keeps tool-use rules, merges redundant.

    ARTIFACTS: 3e_validation.json
```

### Usage

```bash
# Via ADK agent (auto-selects candidates based on quality)
uv run python agents/workflow/skill_evolution_agent/main.py \
    --report eval/runs/.../quality_report.json

# Full demo pipeline (handles traffic, scoring, evolution)
./scripts/demo/skill_evolution/run_demo.sh --quick
```

Candidates are auto-selected based on meaningful_rate: >=90% uses 1,
>=80% uses 3, <80% uses 5. Override with `--candidates N`.

Defaults: agentic analysts, gemini-2.5-flash, 10 workers, 12K char limit,
artifacts saved alongside the report.

Sample candidates: [`candidates/`](../../eval/skill_evolution/reference_runs/v0_baseline_demo/candidates/)
— the 3 consolidation candidates from the best-of-N selection step.

### What to inspect

```bash
ARTS="eval/runs/.../artifacts"

# 3a: partition sizes
python3 -c "import json; print(f'T-: {len(json.load(open(\"$ARTS/3a_t_minus.json\")))} sessions')"

# 3b: patch distribution by root cause
grep -h "^## Root Cause" "$ARTS"/3b_patches_raw/*.md | sort | uniq -c | sort -rn

# 3c: quality gate pass rate
cat "$ARTS/3c_quality_gate.json"

# 3d: prevalence + evolved skill structure
cat "$ARTS/3d_prevalence.txt"
wc -c "$ARTS/3d_evolved_skill.md"
grep "^## " "$ARTS/3d_evolved_skill.md"

# 3e: validation
cat "$ARTS/3e_validation.json"
```

Red flags:
- `3a_t_minus.json` has empty `correction_boundaries` -- scorer ran
  without `--tag-turns`
- `3b_formatted_trajectories.json` has no `Execution Sub-Trajectories`
  -- scorer ran without `--trajectory-samples all`
- `3c_quality_gate.json` shows > 50% rejection -- analyst prompts need tuning
- `3d_prevalence.txt` dominated by HALLUCINATION -- routing issue,
  not skill (use Component 4)
- `3d_evolved_skill.md` > 30KB -- needs `--max-chars`

### Paper mapping

| Aspect | [Trace2Skill] | [AutoSkill] | Our implementation |
|--------|-------------|-----------|-------------------|
| Partitioning (3a) | Binary T+/T- | N/A (online) | 4-way verdict -> binary |
| Error analysts (3b) | Multi-turn agentic, full file system | N/A | Two modes: standard or agentic (2 tools, max 5 turns) |
| Independence (3b) | Frozen skill, no cross-visibility | N/A | Frozen skill, ThreadPoolExecutor -- matches paper |
| Quality gate (3c) | Hard: verified causal chain | N/A | Softer: length + category + structure |
| Consolidation (3d) | Hierarchical tree, 3 guardrails | Pairwise: Add/Merge/Discard | Flat/hierarchical/template-guided |
| Prevalence (3d) | "Inductive reasoning via prevalence" | N/A | 3+ = strong, 1-2 = weak |
| Compaction (3e) | Not addressed | Not addressed | Novel. Priority-ordered rule preservation |
| **Novel** | -- | -- | Template-guided consolidation, best-of-N (6.9pp variance), compaction, correction boundaries as evidence |

---

## Component 4: Co-Evolution Orchestrator

**Module**: `agents/workflow/skill_evolution_agent/coevolve.py`

For multi-agent systems only. Detects which agent is responsible for
failures and targets evolution at the right component.
Invoked via `main.py --mode coevolve` or the `run_coevolution` ADK tool.

### Algorithm

```text
coevolve(quality_report.json, output_dir) -> evolved skills for 1-2 agents

  SUB-STEP 4a: Bottleneck Detection
    For each failure session (up to 30):
    Classify into one of four categories:

    | Category              | Signals                                    | Responsible   |
    |-----------------------|--------------------------------------------|---------------|
    | ROUTING_FAILURE       | Supervisor answered directly, said "I don't | supervisor    |
    |                       | have access" when tool exists               |               |
    | SKILL_FAILURE         | Used tool with wrong keyword, misinterpreted| policy_agent  |
    | TOOL_FAILURE          | Tool returned wrong data, topic missing     | system/data   |
    | ARCHITECTURE_FAILURE  | State loss, date missing, timeout           | system/infra  |

    Recommendation logic:
      routing >= 60% -> evolve supervisor only
      skill >= 60%   -> evolve policy_agent only
      both >= 30%    -> evolve both (supervisor first)

  SUB-STEP 4b: Ordered Evolution
    Sequential (not parallel) because fixing supervisor routing changes
    what data the policy_agent sees.

  SUB-STEP 4c: Summary
    Write co-evolution summary JSON.
```

### Usage

```bash
# Via ADK agent
uv run python agents/workflow/skill_evolution_agent/main.py \
    --report eval/runs/.../quality_report.json --mode coevolve
```

### Paper mapping

| Aspect | [Trace2Skill] | [AutoSkill] | Our implementation |
|--------|-------------|-----------|-------------------|
| Multi-agent | Not addressed | Not addressed | LLM-based failure classification across supervisor / policy_agent / tool / architecture |
| **Novel** | -- | -- | Entirely novel. Neither paper operates on multi-agent systems |

---

## End-to-End: Deploy and Evaluate

After Components 1-3 produce an evolved skill, deploy it and measure
impact:

```bash
RUN_DIR="eval/runs/$(date +%Y-%m-%d_%H%M%S)_evolution"
mkdir -p "$RUN_DIR"

# 1. Backup V0 skill
cp agents/enterprise/policy_agent/skill/SKILL.md "$RUN_DIR/v0_skill.md"

# 2. Deploy evolved skill
cp "$RUN_DIR/artifacts/3d_evolved_skill.md" agents/enterprise/policy_agent/skill/SKILL.md

# 3. Generate traffic with evolved skill
./scripts/demo/generate_traffic.sh \
    --output "$RUN_DIR/v1_traffic.json"

# 4. Score new traffic
./scripts/demo/skill_evolution/score.sh \
    -i "$RUN_DIR/v1_traffic.json" \
    -o "$RUN_DIR/v1_quality_report.json" \
    --report

# 5. Restore V0 skill (ALWAYS)
cp "$RUN_DIR/v0_skill.md" agents/enterprise/policy_agent/skill/SKILL.md
```

### Multi-round evolution (V0 -> V1 -> V2)

```text
Round 1: generate_traffic.sh -> score.sh -> main.py (evolve)
         -> V1 skill -> generate_traffic.sh -> score.sh
Round 2: main.py (evolve from V1 scores) -> V2 skill ->
         generate_traffic.sh -> score.sh -> restore V0
```

Committed reference results (205 conversations):

| Metric | V0 (baseline) | V1 (round 1) | V2 (round 2) |
|--------|---------------|--------------|--------------|
| Meaningful rate | 55.1% | 85.4% (+30.3pp) | 84.4% (−1.0pp, regression) |
| Unhelpful rate | 43.4% | 13.2% (−30.2pp) | 12.2% (−1.0pp) |

Reference run artifacts: `eval/skill_evolution/reference_runs/v0_baseline_demo/`
(`summary.json`). A previous version of this table cited a May 22 2026 run
(54.1% / 97.1% / 98.5%) whose artifact directory
(`reference_runs/breakthrough_may22/`) is not in the repository; those
numbers are withdrawn. On the committed reference, round 2 regresses —
the engine's incumbent-guarded selection keeps V1 deployed in that
case rather than shipping the regression.

### Minimum Failure Threshold

Evolution requires sufficient failure signal. With `--min-failures 30`
(default), the pipeline skips evolution if fewer than 30 sessions are
non-meaningful. This prevents:
- Wasted compute when the skill is already good
- Consolidator producing thinner skills from sparse patches
- Regression from insufficient evidence

Neither paper addresses this scenario — both assume abundant failures.

### Skill Accumulation Problem

Each evolution round rewrites the skill from scratch (Trace2Skill
design). The previous round's content is NOT carried forward — the
consolidator produces a new skill entirely from patches. This means:
- V1 knowledge can be lost in V2 if V2 has fewer patches
- Quality can regress (observed: V1=93.2% → V2=89.8% in one run)

This is a known limitation. Trace2Skill runs single-round only.
AutoSkill solves this with merge-based updates (P_merge: "preserve
the original capability identity, perform semantic union, avoid
regressions") but operates on many small skills, not one monolithic
document. See `docs/skill-evolution/TODO.md` for planned mitigations.

For automated multi-round runs, see `scripts/demo/skill_evolution/run_demo.sh`.

```bash
# Full E2E pipeline
bash scripts/demo/skill_evolution/run_demo.sh --full

# Reuse existing V0 reference data (~1.5h)
bash scripts/demo/skill_evolution/run_demo.sh --full --reuse-v0

# With Claude Code for skill review + ANALYSIS.md
nohup bash scripts/demo/skill_evolution/run_demo_autonomous.sh --reuse-v0 &
```

---

## Key Concepts from the Papers

### Inductive Reasoning via Prevalence (Trace2Skill)

When many independent analysts propose similar patches, that edit
reflects a systematic property of the task, not an idiosyncratic
observation. High prevalence = high confidence. Computed in sub-step 3d.

### Frozen Skill Independence (Trace2Skill)

All analysts see the same frozen skill snapshot. No analyst sees
another's patches. Prevents premature convergence and anchoring bias.

### Asymmetric Analyst Types (Trace2Skill)

Error analysts need deeper investigation (multi-turn, tool access)
because failures have complex root causes. Success analysts only need
single-pass extraction.

### Versioned Skill Identity (AutoSkill)

Skills maintain identity through version numbers, tracking
`evolved_from` lineage. Enables rollback and A/B testing.

### Correction Boundaries (Novel)

Neither paper uses user corrections as direct evidence. Our scorer
extracts the exact `wrong_claim` and `correct_fact` from conversations
where the user corrected the agent. Analysts receive this as factual
evidence.

### Bottleneck Detection (Novel)

Neither paper handles multi-agent systems. Component 4 classifies each
failure by responsible agent before spending compute on evolution.

---

## References

1. Ni, J., Liu, Y., Liu, X., Sun, Y., Zhou, M., et al. (2026).
   [*Trace2Skill: Distill Trajectory-Local Lessons into Transferable Agent
   Skills*](https://arxiv.org/abs/2603.25158). arXiv:2603.25158.

2. Yang, Y., Li, J., Pan, Q., Zhan, B., Cai, Y., et al. (2026).
   [*AutoSkill: Experience-Driven Lifelong Learning via Skill
   Self-Evolution*](https://arxiv.org/abs/2603.01145). arXiv:2603.01145.

[Trace2Skill]: https://arxiv.org/abs/2603.25158
[AutoSkill]: https://arxiv.org/abs/2603.01145
