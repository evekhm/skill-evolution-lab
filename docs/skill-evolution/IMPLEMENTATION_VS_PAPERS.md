# Skill Evolution: Our Implementation vs. the Papers

A detailed comparison of our skill evolution pipeline against the two
foundational papers — **Trace2Skill** and **AutoSkill** — with component-level
implementation details and improvement opportunities.

## The Two Foundational Papers

### Trace2Skill (arXiv:2603.25158)

**Full title**: Trace2Skill: Distill Trajectory-Local Lessons into Transferable
Agent Skills

**Authors**: Jingwei Ni (ETH Zurich), Yihao Liu, Xinpeng Liu, Yutao Sun,
Mengyu Zhou, et al. (Qwen/Alibaba)

**Published**: March 26, 2026

**Core idea**: A batch, three-stage pipeline that mirrors how a human expert
writes an operational manual — accumulate broad experience first, then distill
into a comprehensive guide.

**Stage 1 — Trajectory Generation**:
Run the agent on a diverse set of tasks. Label each trajectory T+ (success) or
T- (failure). Each trajectory includes the full ReAct trace: reasoning steps,
tool calls, observations, and the correctness outcome. The paper uses existing
benchmark datasets (WikiTableQuestions, MATH, etc.) with known correct answers
for labeling. Scale: 200 trajectories with 50+ turns take under 2 GPU-hours.

**Stage 2 — Parallel Multi-Agent Patch Proposal**:
A fleet of independent LLM sub-agents, each assigned exactly one trajectory,
proposes edits to the skill. Two asymmetric analyst types:

- **Success Analyst (A+)**: Single-pass workflow. Cleans the trajectory,
  identifies generalizable behavior patterns that contributed to the correct
  answer, and proposes skill patches. Single LLM call — no tools, no
  investigation loop.
- **Error Analyst (A-)**: Multi-turn agentic loop (ReAct-style). Given a failed
  trajectory, it can inspect files, compare against ground truth, and
  iteratively narrow down the root cause before proposing a patch. Has a
  quality gate: if it cannot establish a verified causal explanation, the
  trajectory is excluded from the patch pool.

Critical constraint: **all analysts operate on a frozen copy of the original
skill** with no visibility into other agents' patches. This independence
prevents premature convergence and preserves the full diversity of
per-trajectory observations.

**Stage 3 — Conflict-Free Patch Consolidation**:
All patches are merged via a recursive tree:

1. Patches are grouped into batches of B_merge
2. Each batch is merged by an LLM consolidator that deduplicates, resolves
   conflicts, and preserves unique insights
3. This repeats up the hierarchy until a single final patch remains
4. Three **deterministic guardrails** enforce correctness:
   - Patches referencing non-existent files are rejected
   - Edits targeting the same line range are flagged as conflicts
   - The updated skill is validated by a format checker

The key principle is **inductive reasoning via prevalence**: edits appearing
consistently across many independent patches are treated as systematic task
properties. Edits appearing in only one or two patches are treated as
idiosyncratic and discarded.

**Key results**:
- Skills evolved by a 35B model improved a 122B model by +57.65pp on
  WikiTableQuestions (cross-model transfer)
- Parallel consolidation outperforms sequential editing by 4-6.8pp in 1/20th
  the time (3 min vs 60 min)
- A single comprehensive skill outperforms retrieval-based memory banks
  (ReasoningBank) by +13.8pp
- Agentic error analysis outperforms single-LLM-call analysis in all settings

### AutoSkill (arXiv:2603.01145)

**Full title**: AutoSkill: Experience-Driven Lifelong Learning via Skill
Self-Evolution

**Authors**: Yutao Yang, Junsong Li, Qianjun Pan, et al. (East China Normal
University, Shanghai AI Laboratory)

**Published**: March 1, 2026

**Core idea**: A continuous, dual-loop system for lifelong skill accumulation
from real user interactions. Treats interaction experience not as memory to
retrieve but as a source of skill formation.

**Loop 1 — Online (at inference time)**:

1. **Query Rewriting**: Resolve context dependence, expose retrieval-critical
   constraints in the user query
2. **Hybrid Skill Retrieval**: Combine dense semantic similarity + BM25
   lexical matching, with threshold-gated top-K selection to find relevant
   skills
3. **Skill-Conditioned Generation**: Inject retrieved skills as context into
   the LLM prompt at inference time

**Loop 2 — Background (after each interaction)**:

1. **Skill Extraction**: From user queries (not model responses), identify
   reusable behavioral patterns — persistent preferences, procedures,
   constraints, conventions
2. **Retrieval-Assisted Management**: Compare each candidate skill against
   existing skills via hybrid retrieval, then a judge decides:
   - **Add**: New distinct capability
   - **Merge**: Same capability, new details to integrate
   - **Discard**: One-off, generic, or noisy
3. **Versioned Merging**: Preserve skill identity while integrating new
   constraints/examples. Version tracking shows evolution history
   (e.g., `0.1.0` -> `0.1.34` = 34 rounds of refinement)

**Key design**: Maintains **many small skills** organized in a SkillBank with
per-user and shared directories. Skills are retrieved at inference time based
on query similarity. Scale: 1,858 skills extracted from 22K+ conversations
(WildChat-1M dataset).

**Key results**:
- Skills evolved at different rates — `professional_text_rewrite` reached
  version 0.1.34 (34 refinement rounds), while specialized skills stayed
  at 0.1.0
- Cross-session and cross-task personalization proven
- Works with any LLM (model-agnostic)

### Papers Compared

| Dimension | Trace2Skill | AutoSkill |
|---|---|---|
| **Learning signal** | Agent execution trajectories (tool calls, reasoning, outcomes) | User dialogue turns (queries, corrections, preferences) |
| **When skills evolve** | Batch: analyze a pool of trajectories, then consolidate | Online: after each interaction turn |
| **Skill count** | One comprehensive skill per domain | Many small skills in a SkillBank |
| **Retrieval** | No retrieval (single skill prepended) | Hybrid dense + BM25 at inference |
| **Analysis depth** | Deep: agentic multi-turn investigation | Shallow: single-pass extraction |
| **Consolidation** | Hierarchical many-to-one merge (prevalence-weighted) | Pairwise: new candidate vs. nearest existing skill |
| **Key strength** | Root-cause analysis, inductive generalization | Real-time adaptation, lifelong accumulation |
| **Key weakness** | Batch-only, not continuous | No agentic investigation, shallow analysis |

The two approaches are **complementary, not competing**: Trace2Skill excels at
deep structural improvements from periodic batch analysis. AutoSkill excels at
continuous incremental adaptation from live interactions.

## Our Implementation

Our system is primarily based on **Trace2Skill**, with selective ideas from
**AutoSkill** for the skill format, plus several original extensions for
multi-agent systems. The pipeline has six major components.

### Component 1: Traffic Generation

**Paper approach (Trace2Skill)**: Uses existing benchmark datasets
(WikiTableQuestions, MATH, TabMWP) with known correct answers. The agent runs
on each task and produces a labeled trajectory. Labeling is deterministic:
the answer is either correct or incorrect per the benchmark's ground truth.

**Paper approach (AutoSkill)**: Uses real user interactions from WildChat-1M
(22K+ conversations). No simulation — real humans asking real questions.

**Our approach**: Fully synthetic multi-turn conversations generated by an LLM
user simulator.

**How it works** (`agents/workflow/traffic_generator/user_simulator.py`):

The simulator plays "Alex," a skeptical new employee who memorized exact policy
facts from an onboarding packet. The onboarding packet is a hardcoded reference
(`POLICY_REFERENCE`) containing precise numbers:

- PTO: 20 days/year, accrued monthly (~1.67/mo), max 5 rollover
- Sick leave: 10 days/year, NO rollover, doctor's note if >3 days
- 401(k): 4% company match, vested after 1 year
- 11 exact 2026 holiday dates
- Explicit out-of-scope topics (salary, promotions, IT, dress code)

Each conversation starts with a question from a predefined question bank
(205 questions across 11 categories: basic policy, edge cases, synonyms,
correction bait, hallucination traps, date-dependent, subtopic, multi-part,
out-of-scope, boundary, calculation). The simulator then:

1. Receives the agent's response
2. **Compacts** verbose responses using regex-based fact extraction
   (`_compact_response`): keeps sentences with numbers, percentages, dates,
   policy keywords; drops filler ("I'd be happy to help", "feel free to ask")
3. Compares against the ground-truth policy reference
4. Picks one of six tags using structured output (Pydantic schema
   `SimulatorResponse`, `response_mime_type="application/json"`):
   - `CORRECTION`: Bot stated a wrong fact — push back with correct data
   - `VERIFY`: Bot gave a generic, non-tool-grounded answer
   - `SPECIFICS`: Bot was vague, no numbers or dates
   - `SCOPE`: Bot answered an out-of-scope question it should have declined
   - `FOLLOWUP`: Answer was correct and specific, ask a related question
   - `END`: Satisfied, say thanks
5. Generates a complete follow-up message as Alex

Turn limits: max 4 turns per conversation. Bias toward ending in later turns
(turn 3 adds "consider wrapping up", turn 4 adds "strongly prefer END").
Temperature: 0.4 for early turns, 0.5 for later turns to avoid repetition.
Concurrency: 10 parallel conversations (configurable up to 20).

**Output**: JSON file with `conversations` array. Each entry has:
`session_id`, `question`, `final_response`, `answered_by`, `latency_s`,
`conversation` (list of turn dicts with `role`, `text`, `tag`), `tool_calls`,
`corrections`, `verifications`.

**Key difference from papers**: Neither paper generates synthetic adversarial
traffic. Trace2Skill relies on benchmark datasets with static ground truth.
AutoSkill relies on organic user interactions. Our simulator is adversarial
by design — it knows the exact right answers and specifically challenges the
agent on hallucinations, vague responses, and scope violations. This produces
higher-density failure trajectories for evolution.

### Component 2: Quality Scoring (LLM Judge)

**Paper approach (Trace2Skill)**: Binary labeling — answer is correct or
incorrect per the benchmark's ground truth. No nuance, no partial credit,
no dimensions.

**Paper approach (AutoSkill)**: Implicit quality signal from user behavior
(corrections, re-asks, satisfaction). No explicit scoring.

**Our approach**: Multi-dimensional LLM-as-judge scoring with structured output.

**How it works**: Two layers of scoring.

**Layer 1 — Basic verdict** (`eval/scoring/llm_judge.py`):

A single Gemini call per conversation classifies the response into one of four
categories using structured output (Pydantic schema `JudgeVerdict`):

- `meaningful`: Directly and substantively addresses the question with specific,
  actionable information
- `declined`: Question is out-of-scope and agent correctly declined — this is
  **correct behavior** and counts as T+
- `unhelpful`: Does NOT meaningfully answer an in-scope question (apologies,
  "I don't have that", generic filler, looping)
- `partial`: Partially addresses but missing key details

The judge prompt injects scope context from `eval/data/agent_context.json` —
a shared knowledge base listing out-of-scope topics. This prevents the judge
from penalizing correct declines.

Settings: model `gemini-2.5-flash`, temperature `0.0`, structured JSON output.

**Layer 2 — Full quality report** (`eval/scoring/score_conversations.py`):

Delegates to the BigQuery Agent Analytics SDK for comprehensive multi-dimension
evaluation. Converts traffic generator conversations to transcript format, then
classifies via the SDK's `classify_sessions_via_api` (Gemini API path, no
BigQuery required).

**Seven scoring dimensions**:

| Dimension | Scale | What it measures |
|---|---|---|
| `response_usefulness` | meaningful / declined / unhelpful / partial | Overall quality (primary metric) |
| `task_grounding` | grounded / ungrounded / no_tool_needed | Did the agent use its lookup tool or hallucinate? |
| `correctness` | 0-2 | Are the facts in the response accurate? |
| `tool_usage` | 0-2 | Did the agent call the right tool with the right arguments? |
| `specificity` | 0-2 | Does the response include specific numbers, dates, limits? |
| `scope_compliance` | 0-2 | Did the agent stay within its defined scope? |
| `first_time_right` | 0-2 | Did the agent get it right on the first attempt, or need corrections? |

Plus transcript-derived counts: `corrections` (user pushed back on a wrong
answer) and `verifications` (user asked agent to confirm). These are either
counted from the simulator tags or inferred via LLM from the conversation
text (`_infer_corrections`).

**Output**: Quality report JSON with:
- `summary`: aggregate metrics (meaningful_rate, unhelpful_rate, correction_rate,
  dimension averages)
- `sessions`: per-session verdicts with all 7 dimension scores, justifications,
  and the full conversation

**Key difference from papers**: Trace2Skill uses binary correct/incorrect.
We score on 7 orthogonal dimensions, which gives the analyst fleet much richer
signal. An agent response can be "correct but vague" (high correctness, low
specificity), "grounded but out-of-scope" (high tool_usage, low
scope_compliance), etc. This lets analysts write more targeted patches.

**Ground truth injection (beyond papers)**: Neither paper addresses the
problem of providing factual ground truth to the judge. We support three
approaches, all implemented:

1. **General ground truth** — a compact factual reference in
   `agent_context.json` injected into every judge prompt.
2. **Per-question golden eval matching** — `--golden-evals` uses
   embedding similarity (gemini-embedding-001, cosine threshold 0.92)
   to find the closest golden Q&A pair for each conversation and injects
   the expected answer into that specific judge prompt.
3. **Auto-generated ground truth** — `extract_ground_truth.py` uses an
   LLM to consolidate golden Q&A pairs into a compact ground truth
   document, automating approach 1 from existing Q&A sets.

Golden eval matching has the most impact on evolved agents (V1+) where
responses are specific enough that factual accuracy matters. For weak
V0 agents that mostly fail outright, general ground truth is sufficient.

### Component 3: Bottleneck Detection

**Paper approach**: Neither Trace2Skill nor AutoSkill addresses multi-agent
systems. Both operate on a single agent. There is no concept of routing vs.
skill failure.

**Our approach**: LLM-based failure classification that determines **which
agent** to evolve before spending compute on evolution.

**How it works** (`agents/workflow/skill_evolution_agent/bottleneck.py`):

**Problem**: In our system, a failed conversation could be caused by:
- The **supervisor** intercepting a question it should have delegated
- The **policy_agent** having insufficient skill instructions
- The **tool** returning wrong or incomplete data
- A **systemic** architecture issue (state loss, timeouts)

Evolving policy_agent's skill when the real problem is supervisor routing
wastes an entire evolution cycle (100+ LLM calls, several minutes, real cost).

**Process**:

1. Extract all failed sessions (unhelpful + partial) from the quality report
2. For each failure (up to 30 for cost control), send the full conversation,
   verdict, quality scores, tool call count, and correction count to Gemini
   with the `BOTTLENECK_CLASSIFIER_PROMPT`
3. Gemini classifies each failure into one of four categories via structured
   JSON output (temperature 0.1):

| Category | Signals | Agent Responsible |
|---|---|---|
| `ROUTING_FAILURE` | Agent answered from "own knowledge", said "I don't have access" when tool exists, supervisor answered a policy question directly | supervisor |
| `SKILL_FAILURE` | Used tool with wrong keyword, misinterpreted tool results, failed on edge cases | policy_agent |
| `TOOL_FAILURE` | Tool returned wrong data, topic not covered | system |
| `ARCHITECTURE_FAILURE` | Multi-turn state loss, date injection missing, timeout | system |

4. Aggregate percentages and apply recommendation logic:
   - `routing >= 60%` → evolve supervisor only
   - `skill >= 60%` → evolve policy_agent only
   - `routing >= 30% AND skill >= 30%` → evolve both
   - Otherwise → evolve the dominant category

**Output**: `BottleneckResult` dataclass with `recommendation` (supervisor /
policy_agent / both / none), `confidence`, per-category failure lists, and
human-readable summary.

**Key difference from papers**: Entirely novel. This is required because we
operate a multi-agent system (supervisor + policy_agent + hr_calculator).
Without bottleneck detection, the system would blindly evolve one agent when
the root cause is in another.

### Component 4: Parallel Analyst Fleet

**Paper approach (Trace2Skill)**:

- **Error Analysts (A-)**: Multi-turn agentic loop. Each analyst gets one failed
  trajectory and the frozen skill. It can inspect files in the task environment,
  compare against ground truth, and iteratively narrow down the root cause.
  Has a hard quality gate: if no verified causal explanation is established,
  the trajectory is excluded.
- **Success Analysts (A+)**: Single-pass. One LLM call per successful
  trajectory extracts generalizable patterns.
- Scale: hundreds of analysts running in parallel on vLLM-served Qwen3.5 models.

**Our approach**: Matches the paper's two-type architecture with both standard
and agentic modes.

**How it works** (`agents/workflow/skill_evolution_agent/evolve.py`,
`agentic_analyst.py`):

**Trajectory partitioning** (`partition_trajectories`):
- T+: sessions with `response_usefulness` = meaningful or declined
- T-: sessions with `response_usefulness` = unhelpful or partial

**Trajectory formatting** (`format_trajectory`):
Each session is formatted into a text block for the analyst containing:
- Full multi-turn conversation (or single-turn question/response)
- Agent that answered (supervisor, policy_agent, hr_calculator)
- Verdict and justification from the LLM judge
- Grounding status (grounded / ungrounded)
- Correction and verification counts
- All 7 dimension scores with reasons

**Error Analysts** — two modes:

*Standard mode* (default): Single LLM call per trajectory. The analyst receives
the `ERROR_ANALYST_PROMPT` system instruction, the frozen skill, and the
formatted trajectory. It must:
1. Identify the root cause (not the symptom)
2. Categorize it: `KEYWORD_GAP`, `MISSING_RULE`, `AMBIGUITY`, `SCOPE_GAP`,
   `HALLUCINATION`
3. Output a structured patch with section, action
   (add_rule / add_mapping / add_edge_case / add_anti_pattern), and exact
   content to add

Model: Gemini 2.5 Flash, temperature 0.3.

*Agentic mode* (`--agentic` flag, `agentic_analyst.py`): Multi-turn
investigation loop inspired by Trace2Skill's A- analysts. Each analyst has
access to two tools via Gemini function calling:
- `lookup_company_policy(topic)` — the same tool the production agent uses
- `get_current_date()` — for date-dependent reasoning

Investigation strategy (from `AGENTIC_ERROR_ANALYST_PROMPT`):
1. Form a hypothesis about the root cause
2. Call `lookup_company_policy` with the **exact keyword the user used**
3. Call it again with the keyword the agent **should have used**
4. Note any gaps between user language and tool topics
5. Compare tool output with what the agent actually said
6. Propose an evidence-based patch with investigation findings

Max 5 tool-call turns per analyst. Additional root cause categories for agentic
mode: `KEYWORD_MAPPING`, `TOOL_USAGE`, `ROUTING_ISSUE`.

The analyst loop (`run_agentic_analyst`):
1. Send initial prompt with frozen skill + trajectory
2. If Gemini responds with function calls, execute them against the real tools
3. Return function results to Gemini
4. Repeat until Gemini responds with text (the patch) or max turns reached
5. Check for `NO_PATCH` marker — if found, return None

**Success Analysts**: Single-pass, one LLM call per trajectory. The
`SUCCESS_ANALYST_PROMPT` instructs the analyst to:
1. Identify what the agent did right that is NOT already in the skill
2. Focus on transferable patterns: `KEYWORD_MAPPING`, `RESPONSE_PATTERN`,
   `DISAMBIGUATION`, `TOOL_USAGE`
3. Output a patch with section, action (reinforce_pattern / add_mapping /
   add_example), and content

Max 15 success trajectories sampled (`max_success_samples`) to balance the
dataset against failures.

**Analyst mode** (`--analyst-mode`): Controls which types to run:
- `both` (default): Error + Success analysts
- `error-only`: Only error analysts
- `success-only`: Only success analysts

**Execution**: `ThreadPoolExecutor` with configurable `max_workers` (default
10). All analysts run in parallel against the frozen skill copy.

**Quality gate** (`passes_quality_gate`): Patches must:
- Be >= 50 characters (reject trivially short outputs)
- Contain at least one root cause category keyword from
  `ROOT_CAUSE_CATEGORIES`

Optional: LLM-based patch scoring (`--score-patches`, via `patch_scoring.py`)
to filter low-quality patches by having another LLM rate each patch on
relevance and specificity before consolidation.

**Key differences from Trace2Skill**:
- Agentic mode is optional (off by default), not the primary mode
- Our analysts have only 2 tools (policy lookup + date), not full file system
  access
- We include 7-dimension quality scores in the trajectory context, giving
  analysts richer signal than the paper's binary pass/fail
- We limit to 5 investigation turns (paper doesn't specify a limit)
- Our quality gate is softer (length + category check vs. the paper's
  requirement for a verified causal explanation)

### Component 5: Patch Consolidation

**Paper approach (Trace2Skill)**: Hierarchical tree consolidation with
deterministic guardrails. Patches are grouped into batches, each batch is
merged by an LLM, intermediate results are merged again, repeating until one
final patch remains. Three hard guardrails: reject non-existent file references,
flag same-line-range conflicts, validate format.

**Paper approach (AutoSkill)**: Pairwise consolidation. Each new candidate
skill is compared against the nearest existing skill via hybrid retrieval.
A judge decides: Add (new skill), Merge (update existing), or Discard.

**Our approach**: Three consolidation modes, plus compaction and best-of-N
selection.

**How it works** (`evolve.py`):

**Mode 1 — Flat Consolidation** (default, `run_consolidator`):

All patches are merged in a single LLM call. The consolidator receives:
- The current (frozen) skill document
- A quality summary (total sessions, meaningful/declined/unhelpful/partial
  counts, meaningful rate)
- All patches concatenated with `---` separators, numbered (Patch 1, Patch 2,
  ...)
- Optional: a structural template to follow

The `CONSOLIDATOR_PROMPT` instructs the LLM to:
1. **Prevalence**: Multi-analyst agreement = strong signal, prioritize
2. **Deduplication**: Same insight from different analysts = include once with
   the clearest wording
3. **Conflict resolution**: Keep the patch with stronger evidence
4. **Preservation**: Keep ALL existing content, only add/refine/reorganize
5. **Structure**: Add new sections as needed (keyword mappings, edge cases,
   anti-patterns, out-of-scope handling)

Output: Complete SKILL.md with YAML frontmatter (version incremented,
`author: skill-evolution`, `evolved_from` tracking).

Model: Gemini 2.5 Flash, temperature 0.2, max_output_tokens 16384.

Safety net: If output is < 50 chars, retry with higher temperature
(+0.3, capped at 1.0).

**Mode 2 — Hierarchical Consolidation** (`--hierarchical`,
`run_hierarchical_consolidation`):

Closer to Trace2Skill's recursive tree merge:
1. Split patches into batches of `batch_size` (default 7)
2. Each batch is merged in parallel by a `run_batch_consolidator` using the
   `HIERARCHICAL_CONSOLIDATOR_PROMPT`, which produces intermediate patch
   documents (NOT final skills)
3. The `HIERARCHICAL_CONSOLIDATOR_PROMPT` explicitly instructs preservation
   of all concrete details: keyword mappings, rules, examples, edge cases,
   anti-patterns. "Err on the side of including too much rather than too
   little."
4. All intermediate results are collected and passed to a final
   `run_consolidator` call that produces the complete SKILL.md

Execution: `ThreadPoolExecutor` for parallel batch consolidation.

Falls back to flat consolidation if there are fewer patches than the batch
size.

**Mode 3 — Template-Guided Consolidation** (`--template`):

The consolidator receives a template file (typically a previous version's
SKILL.md) and is instructed: "Use the template as the structural blueprint.
Your output MUST follow the same section structure, headings, and formatting
style. Integrate analyst patches into the template's sections. Do NOT invent
new sections or reorganize."

This prevents structural drift across evolution rounds — V2 follows V1's
organization, making diffs readable and preventing the consolidator from
reorganizing the entire document on each round.

**Compaction** (`run_compaction`):

Triggered when the evolved skill exceeds `--max-chars`. The `COMPACTION_PROMPT`
(with target character count injected) instructs:
1. Keep ALL mandatory tool-use rules verbatim
2. Keep anti-hallucination directives ("never claim lack of access",
   "do not guess")
3. Merge redundant rules — keep the most specific version
4. Compress keyword mappings — remove obvious entries
5. Remove filler — transition sentences, verbose explanations
6. Preserve section structure

Model: temperature 0.1 for maximal determinism.

Experimental finding: V2 policy_agent skill grew to 45K+ chars. Compaction
to ~10K chars actually **improved** quality by removing redundant prose that
confused the agent.

**Best-of-N Candidate Selection** (`--candidates`):

When `candidates > 1`:
1. Run the analyst fleet once (expensive step — one API call per trajectory)
2. Run the consolidator N times in parallel from the **same patches**
   (stochastic — temperature 0.2 produces variation)
3. Save all candidates to `candidates_dir` as `candidate_1.md`,
   `candidate_2.md`, etc.
4. Each candidate is scored against the full test dataset externally
5. The best-performing candidate is selected

Execution: `ThreadPoolExecutor` with `min(candidates, 5)` workers.

Experimental finding: 10 candidates from identical inputs produced a 6.9pp
quality range (58.0%-64.9%). Best-of-3 gives 97% reliability vs. 70% for
single-shot consolidation.

**Key differences from Trace2Skill**:
- Default is flat (single call), not hierarchical — found to perform better
  at our scale (~100 patches)
- No deterministic guardrails (no file-existence checks, no line-range conflict
  detection, no format validation)
- Template-guided consolidation is novel (not in any paper)
- Best-of-N selection is novel
- Compaction is novel (papers don't address skill bloat)

### Component 6: Cross-Agent Co-Evolution

**Paper approach**: Neither paper handles multi-agent systems. Both evolve a
single agent's skill in isolation.

**Our approach**: Orchestrated evolution across multiple agents with
bottleneck-driven prioritization.

**How it works** (`agents/workflow/skill_evolution_agent/coevolve.py`):

1. **Load report and detect bottleneck**: Calls `detect_bottleneck()` from
   Component 3 to classify failures and get a recommendation
2. **Determine evolution order**:
   - `supervisor` → evolve supervisor only
   - `policy_agent` → evolve policy_agent only
   - `both` → evolve supervisor **first**, then policy_agent (routing fix
     enables better data for policy agent evolution)
   - `none` → skip (no failures)
3. **Run evolution**: For each agent to evolve:
   - Use the agent's `skill_dir` from `DEFAULT_AGENT_CONFIGS`
   - Run the full `evolve()` pipeline (analyst fleet → consolidation)
   - Save evolved skill + candidates to `output_dir`
4. **Save co-evolution summary**: JSON with bottleneck analysis, evolved agents,
   timing

Default agent configs:
- `supervisor`: `agents/enterprise/knowledge_supervisor/app/skill/`
- `policy_agent`: `agents/enterprise/policy_agent/skill/`

Default best-of-N: 3 candidates per agent.

Sequential evolution (not parallel) because supervisor routing affects
policy_agent data quality — evolving them simultaneously would mean
policy_agent evolves on data that includes routing failures it can't fix.

## Architecture Diagram

Use this prompt with an image generator to create a technical diagram of
our implementation:

```text
Create a clean, professional technical architecture diagram titled
"Skill Evolution Pipeline" with a white background and a modern flat
design style using blues, teals, and grays.

The diagram flows top-to-bottom through five horizontal layers:

LAYER 1 — TRAFFIC & EVALUATION (top):
Three connected boxes in a row:
- "Traffic Generator" (icon: chat bubbles) labeled "User simulator 'Alex'
  with ground-truth policy reference, 205 questions x 11 categories,
  multi-turn with CORRECTION/VERIFY/SPECIFICS/SCOPE/FOLLOWUP/END tags,
  up to 4 turns, 10 concurrent conversations"
- Arrow flowing right to "LLM Judge" (icon: scales) labeled "7-dimension
  scoring: usefulness, grounding, correctness, tool_usage, specificity,
  scope_compliance, first_time_right. Model: Gemini 2.5 Flash, temp 0.0,
  structured JSON output"
- Arrow flowing right to "Bottleneck Detector" (icon: magnifying glass)
  labeled "Per-failure LLM classification into ROUTING_FAILURE /
  SKILL_FAILURE / TOOL_FAILURE / ARCHITECTURE_FAILURE. Threshold logic:
  >=60% routing → evolve supervisor, >=60% skill → evolve policy_agent,
  both >=30% → evolve both"

LAYER 2 — TRAJECTORY PARTITIONING:
A single box receives from Layer 1. Two arrows diverge downward:
- Left arrow labeled "T- (unhelpful + partial)" goes to red-tinted area
- Right arrow labeled "T+ (meaningful + declined)" goes to green-tinted
  area

LAYER 3 — PARALLEL ANALYST FLEET (widest layer):
A prominent banner across the top reads "All analysts see FROZEN skill
copy — independent, parallel, no cross-talk
(ThreadPoolExecutor, max 10 workers)".

Left side (red-tinted): Multiple parallel boxes labeled "Error Analyst 1",
"Error Analyst 2", ... "Error Analyst N". Each has a small tag showing
two modes: "Standard: single LLM call, temp 0.3" and "Agentic: multi-turn
loop with lookup_company_policy() + get_current_date() tools, max 5 turns".
Root cause categories listed: KEYWORD_GAP, MISSING_RULE, AMBIGUITY,
SCOPE_GAP, HALLUCINATION.

Right side (green-tinted): Multiple parallel boxes labeled "Success
Analyst 1", "Success Analyst 2", ... "Success Analyst M (max 15)".
Each shows "Single-pass, temp 0.3". Pattern categories: KEYWORD_MAPPING,
RESPONSE_PATTERN, DISAMBIGUATION, TOOL_USAGE.

All analyst boxes have arrows flowing down through a filter labeled
"Quality Gate: >=50 chars + must contain root cause category".

LAYER 4 — CONSOLIDATION:
Three alternative paths shown side-by-side:
- "Flat Consolidation (default)" — single LLM call, prevalence-weighted
  merge, temp 0.2, max 16K output tokens
- "Hierarchical Consolidation" — tree diagram with batches of 7 merging
  upward through intermediate consolidators to final merge
- "Template-Guided" — merge constrained to follow structural blueprint
  from previous version

All three paths converge into a "Best-of-N Selection" box (icon: trophy)
labeled "Generate N candidates from same patches (stochastic consolidation),
score each on full test data, pick best. Default N=3, addresses 6.9pp
consolidation variance".

Below that, an optional "Compaction" step (icon: compress arrows) labeled
"If > max_chars: keep tool-use rules + anti-hallucination, merge redundant
rules, compress keyword mappings, remove filler. Temp 0.1. Example: 45K →
10K chars with quality improvement".

LAYER 5 — OUTPUT (bottom):
A document icon labeled "Evolved SKILL.md" with YAML frontmatter visible:
"version: N+1, author: skill-evolution, evolved_from: N". An arrow loops
back to Layer 1 with a dashed line labeled "Next Evolution Round
(V0→V1: +1.5pp, V1→V2: +33.1pp)".

SIDE PANEL (right): A vertical box labeled "Cross-Agent Co-Evolution
(coevolve.py)" showing two stacked agent icons: "Supervisor" (top) and
"Policy Agent" (bottom), with an arrow labeled "evolve routing first,
then skill" flowing downward. A note: "Sequential, not parallel — routing
fix enables better policy_agent data".

Style: technical diagram suitable for a conference talk or blog post.
No gradients, solid colors with subtle shadows. Labels in a clean
sans-serif font. All boxes have rounded corners. Include file path
annotations next to each component (e.g., "evolve.py", "bottleneck.py",
"user_simulator.py").
```

## Detailed Comparison Table

| Dimension | Trace2Skill (Paper) | AutoSkill (Paper) | Our Implementation |
|---|---|---|---|
| **Traffic source** | Benchmark datasets (WikiTableQuestions, MATH, TabMWP) with known answers | Real user interactions (WildChat-1M, 22K+ conversations) | Synthetic: LLM user simulator with hardcoded ground-truth policy data, 205 questions x 11 categories, adversarial multi-turn follow-ups |
| **Trajectory labeling** | Binary: correct / incorrect per benchmark ground truth | Implicit (user satisfaction) | 4-way: meaningful, declined (both T+), unhelpful, partial (both T-) |
| **Scoring dimensions** | 1 (binary correctness) | 0 (implicit) | 7: usefulness, grounding, correctness, tool_usage, specificity, scope_compliance, first_time_right + correction/verification counts |
| **Error analysts** | Multi-turn agentic (default), full file system access, quality gate requires verified causal explanation | N/A | Two modes: standard (single-pass, default) and agentic (opt-in, 2 tools: policy lookup + date, max 5 turns, quality gate: 50 chars + root cause category) |
| **Success analysts** | Single-pass | N/A | Single-pass, max 15 sampled |
| **Analyst independence** | Frozen skill copy, no cross-visibility | N/A | Frozen skill copy, ThreadPoolExecutor parallelism — matches paper |
| **Consolidation** | Hierarchical tree: recursive batch merge with deterministic guardrails | Pairwise: new vs. nearest existing, Add/Merge/Discard | Three modes: flat (default), hierarchical (optional), template-guided (optional). No deterministic guardrails |
| **Skill structure** | SKILL.md + populated `references/` subdirectory | SKILL.md with tags, triggers, versioned metadata | SKILL.md with YAML frontmatter (version, author, evolved_from). `references/` defined but empty |
| **Skill count** | One per domain | Many in a SkillBank, retrieved at inference | One per agent (supervisor, policy_agent) |
| **Retrieval at inference** | None (prepended to context) | Hybrid dense + BM25 | None (prepended to context) — matches Trace2Skill |
| **Multi-agent** | Single agent | Single agent | Multi-agent with cross-agent co-evolution and bottleneck detection (novel) |
| **Best-of-N** | Not described | Not described | Generate N candidates, score each, pick best. Addresses 6.9pp variance (novel) |
| **Compaction** | Not described | Not described | Distills bloated skills (45K→10K chars) while preserving effectiveness (novel) |
| **Template-guided** | Not described | Not described | Structural blueprint constrains section organization across rounds (novel) |
| **Multi-round** | Single round shown | Continuous (versions accumulate) | Multi-round: V0→V1→V2. Two rounds essential — V1 learns failures, V2 writes strong fixes (novel finding) |
| **Cross-model transfer** | Proven: 35B→122B, +57.65pp | Proven cross-session/task | Not yet tested (Flash→Flash only) |
| **Deployment** | Research prototype (vLLM serving) | SDK/Web UI plugin | Production: Cloud Run Job (weekly cron), GCS archival, GitHub PR integration, CI quality gates |
| **Model** | Qwen3.5 (35B, 122B) open-source | Various (model-agnostic) | Gemini 2.5 Flash (all components) |

## Novel Extensions (Not in Either Paper)

### 1. Bottleneck Detection + Cross-Agent Co-Evolution

Neither paper handles multi-agent systems. Our system first classifies each
failure by responsible agent (supervisor routing vs. policy_agent skill vs.
tool vs. architecture), then targets evolution at the right component. When
both agents need work, supervisor evolves first because fixing routing enables
cleaner data for policy_agent evolution.

### 2. Best-of-N Candidate Selection (score-based + incumbent-guarded)

Consolidation is stochastic. We discovered that 10 candidates from identical
patches produced a 6.9pp quality range (58.0%-64.9%). We generate N candidates
and **score each on the SAME eval set used everywhere else in the loop**, then
keep the best candidate **only if it beats the V0 incumbent by a margin** —
otherwise we keep V0. This realises Trace2Skill's objective P(S\*) > P(S₀) and
AutoSkill's "avoid regressions" rule, and makes V1 ≥ V0 guaranteed.

Implementation: `evolve.py` `evolve(score_fn=..., incumbent_score=...)`; the
`score_fn` (wired from both `run_evolution` and `coevolve`) scores a candidate
via `score_candidate` on `EVAL_QUESTIONS_FILE`. Co-evolution is **sequential**
(supervisor first, then policy_agent scored against the improved routing) so
per-candidate scoring does not corrupt the shared `SKILL.md` files.

> **Earlier bug (fixed):** selection used to pick the *median-by-character-count*
> candidate (`evolve.py`), so a worse-scoring skill could ship — we observed
> V1 regressing below V0. The score-based incumbent guard removes that risk.

> **Caveat:** each candidate is scored on its own fresh traffic run, so on
> small eval sets (≤40q) ±10pp run-to-run noise can swamp the signal and the
> guard conservatively keeps V0. Use ≥150q for a reliable comparison.

### 3. Compaction Pass

Evolved skills balloon (V2 policy_agent was 45K chars). The compaction pass
distills to ~10K chars while actually improving quality by removing redundant
prose that confused the agent. Priority: tool-use rules > anti-hallucination
directives > keyword mappings > filler.

### 4. Template-Guided Consolidation

Prevents structural drift across evolution rounds. V2 follows V1's section
organization instead of the consolidator reinventing the layout each time.
Makes diffs readable and ensures stable skill structure.

### 5. Multi-Round Evolution

Papers show single-round results. We found two rounds essential: V1 exposes
the failure landscape (+1.5pp), V2 writes strong directives to fix it
(+33.1pp). The modest V1 gain is not a failure — it provides the failure
signal that V2 learns from.

### 6. Synthetic Adversarial Traffic

Instead of benchmark datasets (Trace2Skill) or real traffic (AutoSkill), we
generate targeted multi-turn conversations with a simulated user who knows
the ground truth and specifically challenges hallucinations, vague responses,
and scope violations.

### 7. 7-Dimension Quality Scoring

Trace2Skill uses binary pass/fail. Our 7-dimension scoring captures orthogonal
failure modes, giving analysts richer signal for more targeted patches.

## What Could Still Be Improved

### Recently implemented (this iteration)

- **Incumbent-guarded, score-based best-of-N** — never ships a skill worse than
  V0 (was median-by-size). Fixes observed V1<V0 regressions.
- **Consistent eval set across the whole loop** — V0 scoring, evolution, and
  candidate scoring all use the same `EVAL_QUESTIONS_FILE` (was: evolve on the
  quick set, validate candidates on the full set — an invalid comparison).
- **Sequential co-evolution** — supervisor first, then policy_agent scored
  against the improved routing (was parallel, contradicting the design).
- **3-gap failure taxonomy + `addressable_meaningful_rate`** — separates
  skill_gap (evolution-fixable) from knowledge_gap (add a fact) and tool_gap
  (build a tool); gives a fair denominator for what evolution can move.

### Still open — High Impact — Directly from the Papers

**0. Held-out validation split (Trace2Skill §2.1)**

We now score candidates on the same set we evolve from, which is internally
consistent but still risks overfitting to the patch-generating questions. A
disjoint evolve/validate split (e.g. 70/30) would measure true generalization.
Patches come only from the evolve split; selection scores only on validate.

**0b. Accumulative / identity-preserving merge (AutoSkill P_merge)**

Each round still rewrites SKILL.md from scratch, so prior-round rules can be
lost (the V1→V2 content-loss regressions). Feed the previous evolved skill as
the base and instruct a semantic union that preserves every existing rule
unless a patch explicitly overrides it, then diff to confirm nothing was
silently dropped.

### High Impact — Directly from the Papers

**1. Make Agentic Error Analysts the Default**

Trace2Skill shows agentic multi-turn analysts outperform single-pass in ALL
settings. Our `--agentic` mode exists but is off by default. The paper's A-
analysts have full file system access and no turn limit. Ours are limited to
2 tools and 5 turns.

*What to do*: Make `--agentic` the default. Expand the tool set to include:
- `read_skill_section(section_name)` — inspect specific parts of the skill
- `search_past_conversations(keyword)` — find similar past failures
- `diff_skill_versions(v1, v2)` — compare what changed between versions
- `list_tool_topics()` — discover all available tool arguments

Remove the 5-turn limit or raise it to 10. Add the paper's hard quality gate:
reject patches where the analyst cannot provide a verified causal chain from
root cause to proposed fix.

**2. Add Deterministic Guardrails to Consolidation**

Trace2Skill uses three hard guardrails:
- Reject patches referencing non-existent files
- Flag edits targeting the same line range
- Validate the output format

We have only a soft quality gate (50 chars + category keyword). Adding
structural validation would reduce consolidation failures:
- Verify valid YAML frontmatter (parseable, version incremented)
- Verify all sections from the current skill are preserved
- Verify no markdown syntax errors
- Check output length is reasonable (not 10x original or < 50% of original)

**3. Populate `references/` Subdirectory**

Both papers and our directory layout define `references/`, `assets/`, and
`scripts/` subdirectories, but ours are empty. Trace2Skill shows that
low-support observations (edge cases found in only 1-2 trajectories) naturally
get routed to `references/` files while high-prevalence SOPs stay in the main
SKILL.md.

*What to do*: Modify the consolidator prompt to output two artifacts:
- `SKILL.md` — high-prevalence rules (3+ analysts proposed similar patches)
- `references/edge_cases.md` — low-prevalence observations (1-2 analysts)

This prevents SKILL.md from bloating and makes compaction less necessary.

**4. Add Online Skill Retrieval (from AutoSkill)**

We use zero AutoSkill ideas at inference time. Currently, the entire SKILL.md
(~10K chars) is prepended to every query regardless of relevance.

*What to do*: Split the skill into semantic sections, embed them, and retrieve
only the relevant sections per query using hybrid retrieval (dense + BM25).
This reduces prompt size and improves focus. Most impactful when the skill
grows beyond ~15K chars.

### Medium Impact — Engineering Improvements

**5. Cross-Model Transfer Testing**

Trace2Skill's most impressive result is cross-model transfer (+57.65pp from
35B→122B). We've only tested Flash→Flash. Running evolved skills on Gemini Pro
or a different model family would validate generalization.

**6. Automatic Evolution Triggering**

Currently batch-only (manual trigger or weekly cron). AutoSkill's online loop
extracts skills after each interaction. A lightweight version: after every N
production conversations, check if quality dips below a threshold and trigger
evolution automatically.

**7. Patch Provenance Tracking**

We lose the connection between final skill content and contributing patches.
Trace2Skill counts patch prevalence (e.g., "178/323 patches proposed formula
recalculation verification"). Adding a provenance log — which patches survived
consolidation and how many independent analysts proposed similar ideas — would
improve interpretability.

**8. Automated Skill Rollback**

We track versions and keep snapshots but have no automated rollback. If an
evolved skill degrades quality, the system should automatically revert to the
previous version and flag the regression.

**9. Success/Failure Ratio Balancing**

We cap success samples at 15 but don't balance against failure count. If there
are 5 failures and 100 successes, the 15 success analysts could drown out the
5 error analysts during prevalence-weighted consolidation. Consider matching
the success sample count to the failure count.

**10. Continuous Drift Detection**

Neither paper addresses concept drift (policies change, new topics emerge).
Our `agent_context.json` is manually maintained. An AutoSkill-style monitor
that flags when production queries hit topics not covered by any existing
skill section would close this gap.

## Experimental Results

Results from V0→V1→V2 evolution on 205 multi-turn conversations:

| Metric | V0 (baseline) | V1 (round 1) | V2 (round 2) |
|---|---|---|---|
| Meaningful rate | 59.5% | 61.0% (+1.5pp) | 94.1% (+33.1pp) |
| Skill size | 574 chars | ~5K chars | ~10K chars (after compaction from 45K) |

**Per-category improvements (V0→V2)**:

| Category | V0 | V2 | Delta |
|---|---|---|---|
| Correction bait | 38% | 100% | +62pp |
| Date-dependent | 31% | 92% | +62pp |
| Subtopic | 29% | 88% | +59pp |
| Synonym | 55% | 100% | +45pp |
| Hallucination trap | 50% | 95% | +45pp |

**Key finding**: The biggest improvement came from fixing supervisor routing.
V0's supervisor answered policy questions itself (hallucinating). V2's
supervisor always delegates to policy_agent, which uses the lookup tool.

## References

1. Ni, J., Liu, Y., Liu, X., Sun, Y., Zhou, M., et al. (2026).
   *Trace2Skill: Distill Trajectory-Local Lessons into Transferable Agent
   Skills*. arXiv:2603.25158.

2. Yang, Y., Li, J., Pan, Q., Zhan, B., Cai, Y., et al. (2026).
   *AutoSkill: Experience-Driven Lifelong Learning via Skill Self-Evolution*.
   arXiv:2603.01145.

3. Anthropic. (2026). *Skills Framework for Claude Code*.
