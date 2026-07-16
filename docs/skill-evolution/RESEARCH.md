# Automatic Skill Evolution for LLM Agents

## From Reactive Fixes to Self-Improving Agent Skills

**Research Review & Application to the Knowledge Supervisor Demo**

---

## Executive Summary

Two recent papers present complementary frameworks for automatically
improving LLM agent capabilities through **skill evolution** -- turning
agent execution experience into explicit, reusable, transferable skill
documents without any model retraining:

| Paper | Core Idea | Approach |
|-------|-----------|----------|
| **Trace2Skill** (Alibaba/Qwen, Mar 2026) | Distill lessons from execution trajectories into comprehensive skills | Parallel analyst fleet + hierarchical patch consolidation |
| **AutoSkill** (ECNU/Shanghai AI Lab, Mar 2026) | Lifelong learning via skill self-evolution from user interactions | Online extraction + retrieval-assisted maintenance + versioned merging |

Both papers formalize skills as structured, human-readable artifacts
(SKILL.md files with metadata, instructions, and auxiliary resources)
that are prepended to the agent's context at inference time. No model
parameters are updated -- all improvement comes from evolving the skill
document itself.

**Key insight for our demo**: Our current quality loop fixes agent
prompts reactively, one issue at a time. These papers show we can
instead analyze execution trajectories holistically and distill them
into comprehensive, self-improving skills that transfer across models
and generalize to unseen scenarios.

---

## Paper 1: Trace2Skill

**Full Title**: Trace2Skill: Distill Trajectory-Local Lessons into
Transferable Agent Skills

**Authors**: Jingwei Ni (ETH Zurich), Yihao Liu, Xinpeng Liu, Yutao
Sun, Mengyu Zhou, et al. (Qwen/Alibaba)

**Published**: March 26, 2026 -- arXiv:2603.25158

**Code**: Uses Qwen3.5 models (35B and 122B), vLLM serving

### Problem Statement

Manual skill authoring is a scalability bottleneck. Automated approaches
either rely on shallow parametric knowledge (which doesn't help) or
update skills sequentially from individual trajectories (which causes
fragmentation and overfitting). The paper identifies two key failure
modes of existing online approaches:

1. **Skill Fragmentation**: Creating many narrow skills instead of one
   comprehensive guide, leading to retrieval difficulties
2. **Sequential Overfitting**: Editing skills reactively based on
   individual trajectories, causing premature convergence and order
   dependence

### The Trace2Skill Algorithm

The framework operates in three stages, mirroring how human experts
author skills: accumulate broad experience first, then distill into a
comprehensive guide.

#### Stage 1: Trajectory Generation

Run the agent on a diverse set of tasks using the current skill,
producing labeled trajectories:

- **T+** (successes): Trajectories where the agent answered correctly
- **T-** (failures): Trajectories where the agent failed

Each trajectory includes the full ReAct trace: reasoning steps, tool
calls, observations, and the correctness outcome. This stage is fully
parallelizable (200 trajectories with 50+ turns take < 2 GPU-hours).

#### Stage 2: Parallel Multi-Agent Patch Proposal

A **fleet of analyst sub-agents**, each assigned to a single trajectory,
independently proposes edits to the skill. Two asymmetric analyst types:

**Success Analyst (A+)**: Single-pass workflow. Cleans the trajectory,
identifies generalizable behavior patterns that contributed to the
correct answer, and proposes skill patches. Efficient because successful
trajectories require no interactive diagnosis.

**Error Analyst (A-)**: Multi-turn agentic loop (ReAct-style). Given a
failed trajectory, it can inspect files, compare against ground truth,
and iteratively narrow down the root cause before proposing a patch.
Quality gate: if the analyst cannot establish a verified causal
explanation, the trajectory is excluded from the patch pool. This
ensures every patch is grounded in a verified failure mechanism.

Critical design decision: **All analysts operate on a frozen copy of
the original skill** with no visibility into other agents' patches.
This independence prevents premature convergence and preserves the
full diversity of per-trajectory observations.

#### Stage 3: Conflict-Free Patch Consolidation

All patches are merged hierarchically into a single coherent skill
update:

1. Patches are grouped into batches of B_merge
2. Each batch is synthesized into a consolidated patch via an LLM
   merge operator that deduplicates, resolves conflicts, and
   preserves unique insights
3. This repeats up the hierarchy until a single final patch remains
4. Three deterministic guardrails enforce correctness:
   - Patches referencing non-existent files are rejected
   - Edits targeting the same line range are flagged as conflicts
   - The updated skill is validated by a format checker

**Inductive reasoning**: The hierarchical merge identifies **prevalent
patterns** -- edits appearing consistently across independent patches
-- on the grounds that recurring observations across diverse
trajectories are more likely to reflect systematic task properties.
Edits appearing in only one or few patches are treated as idiosyncratic
and discarded.

**Self-contained pipeline**: The same LLM that generates trajectories
also proposes patches and consolidates them. No external teacher model
required. Open-source models as small as 35B work.

### Two Evolution Modes

| Mode | Starting Point | Goal |
|------|---------------|------|
| **Skill Deepening** | Human-written skill | Refine and strengthen an existing good skill |
| **Skill Creation** | LLM-drafted parametric skill (no trajectory grounding) | Build a useful skill from scratch |

### Key Results

- Skills evolved by a 35B model improved a 122B model by up to **+57.65
  percentage points** on WikiTableQuestions (cross-model transfer)
- **Parallel consolidation outperforms sequential editing** (+ 4-6.8 pp)
  in 1/20th the time (3 min vs 60 min)
- A single comprehensive skill outperforms retrieval-based memory banks
  (ReasoningBank) by +13.8 pp
- **Agentic error analysis** (multi-turn investigation with file access)
  outperforms single-LLM-call analysis in all settings
- Works across domains: spreadsheets, math reasoning, visual QA

### What the Evolved Skills Look Like

The 122B Deepening +Combined run produced 323 patches that consolidated
into SOPs in the main SKILL.md. The four most prevalent themes:

| SOP | Patch Count | What It Encodes |
|-----|-------------|----------------|
| Formula recalculation & write-back verification | 178/323 | Run recalc.py after every formula write, reopen with data_only=True |
| Tool selection: openpyxl over pandas.to_excel() | 177/323 | pandas.to_excel() silently destroys formula relationships |
| Explicit read-back verification | 138/323 | After writing, reopen and confirm every target cell |
| Structural-edit safety | 53/323 | Delete rows in descending order to prevent index-shift corruption |

Lower-support observations were routed to `references/` subdirectory
files -- the hierarchy (general principles in SKILL.md, edge cases in
references/) emerged automatically from trajectory evidence.

---

## Paper 2: AutoSkill

**Full Title**: AutoSkill: Experience-Driven Lifelong Learning via Skill
Self-Evolution

**Authors**: Yutao Yang, Junsong Li, Qianjun Pan, et al. (East China
Normal University, Shanghai AI Laboratory)

**Published**: March 1, 2026 -- arXiv:2603.01145

**Code**: Open-source at github.com/ECNU-ICALK/AutoSkill

### Problem Statement

Users repeatedly express stable preferences and requirements (reduce
hallucinations, follow writing conventions, avoid technical jargon), but
LLM agents fail to accumulate personalized capabilities across sessions.
Interaction experience is seldom consolidated into reusable knowledge.

### The AutoSkill Framework

AutoSkill treats interaction experience not as memory to retrieve but as
a source of **skill formation**. It operates two coupled loops:

#### Loop 1: Skill-Enhanced Response Generation (Online)

1. **Query Rewriting**: Resolve context dependence, expose
   retrieval-critical constraints
2. **Hybrid Skill Retrieval**: Combine dense semantic similarity + BM25
   lexical matching, threshold-gated top-K selection
3. **Skill-Conditioned Generation**: Inject retrieved skills as context
   into the LLM prompt

#### Loop 2: Skill Evolution (Background)

1. **Skill Extraction**: From user queries (not model responses),
   identify reusable behavioral patterns -- persistent preferences,
   procedures, constraints, conventions
2. **Retrieval-Assisted Management**: Compare each candidate against
   existing skills using hybrid retrieval, then a judge decides:
   - **Add**: New distinct capability
   - **Merge**: Same capability, new details to integrate
   - **Discard**: One-off, generic, or noisy
3. **Versioned Merging**: When merging, preserve skill identity while
   integrating new constraints/examples. Version bump tracks evolution
   (e.g., `0.1.0` -> `0.1.34` = 34 rounds of refinement)

### Skill Representation

Each skill is a structured SKILL.md artifact:

```yaml
name: professional_text_rewrite
description: Rewrites text to enhance fluency and professionalism
version: 0.1.34
tags: [rewrite, editing, professional, paraphrase]
triggers: ["rewrite this professionally", "improve this text"]
```

With sections: Role & Objective, Constraints & Style, Core Workflow,
Output Format, Anti-Patterns, Interaction Workflow.

### Key Design Principles

1. **Explicit skill representation** -- inspectable, editable, portable
2. **Continuous but controlled evolution** -- extract reusable patterns,
   discard noise, prevent duplication
3. **Low-friction deployment** -- model-agnostic plugin layer (SDK, Web
   UI, OpenAI-compatible proxy)
4. **Training-free** -- no parameter updates, all improvement via
   external skill artifacts

### Storage Layout

```
SkillBank/
  Users/<user_id>/
    <skill-slug>/SKILL.md
    scripts/, references/, assets/
  Common/           # Shared skills
  vectors/          # Persistent vector caches
```

### Results

Applied to WildChat-1M (22K+ conversations), AutoSkill extracted 1,858
skills across programming, writing, data/AI, and general tasks. Skills
evolved at different rates -- a `professional_text_rewrite` skill
reached version 0.1.34 (34 refinement rounds), while specialized skills
remained at 0.1.0.

---

## Comparison: Trace2Skill vs. AutoSkill

| Dimension | Trace2Skill | AutoSkill |
|-----------|-------------|-----------|
| **Learning signal** | Agent execution trajectories (tool calls, reasoning traces, outcomes) | User dialogue turns (queries, corrections, preferences) |
| **When skills evolve** | Batch: analyze a pool of trajectories, then consolidate | Online: after each interaction turn |
| **Analysis approach** | Parallel fleet of analyst sub-agents with agentic error investigation | Single-pass extraction + judge + merge modules |
| **Consolidation** | Hierarchical many-to-one merge with inductive reasoning | Pairwise: new candidate vs. nearest existing skill |
| **Skill structure** | SKILL.md + references/ directory (hierarchical depth) | SKILL.md with metadata (flat, versioned) |
| **Transferability** | Proven cross-model and cross-domain transfer | Proven cross-session and cross-task personalization |
| **Scale** | 200 trajectories, open-source 35B models sufficient | 22K+ conversations, works with any LLM |
| **Key strength** | Deep root-cause analysis of failures, inductive generalization | Real-time adaptation to user preferences, lifelong accumulation |
| **Key weakness** | Batch-only (not continuous), needs labeled success/failure | Shallow analysis (single LLM call), no agentic investigation |

### Complementary Strengths

The two approaches are **not competing but complementary**:

- **Trace2Skill** excels at **deep, structural improvements** -- finding
  systematic patterns in how agents fail and encoding robust SOPs.
  It's best for periodic "deep dives" into agent quality.

- **AutoSkill** excels at **continuous, incremental adaptation** --
  capturing user preferences and evolving skills in real-time. It's
  best for ongoing personalization and drift tracking.

A combined system would use AutoSkill's online loop for real-time skill
accumulation and Trace2Skill's batch analysis for periodic deep
consolidation and quality improvement.

---

## Application to Our Knowledge Supervisor Demo

### Previous Architecture (Reactive, Issue-by-Issue)

```
Traffic -> BigQuery -> Quality Agent -> Individual Issues
  -> Remediation Agent (1 fix per issue) -> PR -> CI -> Deploy
```

**Limitations** (as identified by Trace2Skill):
- Sequential: fix order matters, later fixes may conflict with earlier
- Fragmented: each fix addresses one narrow gap
- Reactive: waits for problems to manifest before acting
- No cross-trajectory pattern mining
- Prompts are flat strings, not structured skill directories

### Proposed Architecture (Skill Evolution)

```
Traffic -> BigQuery -> Trajectory Pool (T+/T-)
  -> Parallel Analyst Fleet (Error + Success Analysts)
  -> Hierarchical Patch Consolidation
  -> Comprehensive Skill Update -> PR -> CI -> Deploy
```

With an additional online loop:
```
User Query -> Skill Retrieval -> Skill-Augmented Response
  -> Background: Skill Extraction + Maintenance
```

### What Changes

#### 1. Skill Directory Structure (replaces flat prompts.py)

Instead of:
```python
# agents/enterprise/policy_agent/prompts.py
CURRENT_PROMPT = "You are a helpful company information assistant..."
```

Use a structured skill directory:
```
agents/enterprise/policy_agent/skill/
  SKILL.md              # Main procedural guidance
  references/
    expense_policies.md  # Edge cases for expense handling
    holiday_calendar.md  # Holiday-specific rules
    decline_patterns.md  # How to decline out-of-scope gracefully
```

The SKILL.md follows the Anthropic skill format with sections:
- Role & Objective
- In-Scope Topics (allowlist)
- Tool Usage Rules
- Response Constraints & Anti-Patterns
- Known Edge Cases
- Decline Protocol

#### 2. New Workflow Agents

| Current Agent | Replacement | What Changes |
|---------------|-------------|--------------|
| Quality Agent | **Trajectory Collector + Quality Scorer** | Instead of creating issues per failure, partition sessions into T+/T- and trigger skill evolution |
| Remediation Agent | **Skill Evolution Agent** | Instead of fixing one issue, analyze all trajectories and produce a comprehensive skill update |
| (none) | **Error Analyst** (sub-agent fleet) | Each analyst gets one failed trajectory + frozen skill, investigates root cause via multi-turn agentic loop |
| (none) | **Success Analyst** (sub-agent fleet) | Each analyst gets one successful trajectory, extracts generalizable patterns in single pass |
| (none) | **Patch Consolidator** | Hierarchically merges all analyst patches into a single coherent skill update |

#### 3. Revised Demo Scenarios

**Scenario 1: Skill Deepening (replaces current Scenario 1)**

Starting state: Human-written V1 skill (basic prompt covering PTO,
sick leave, remote work). Agent handles some topics well but has gaps.

1. Traffic generator sends 50+ diverse questions (in-scope, edge cases,
   out-of-scope)
2. All sessions logged to BigQuery with full tool-call traces
3. Trajectory Collector partitions into T+ (well-answered) and
   T- (failures, infinite loops, hallucinations)
4. **Parallel analyst fleet** deploys:
   - 15 Error Analysts examine T- trajectories (why did the agent loop
     on salary questions? why did it hallucinate expense limits?)
   - 10 Success Analysts examine T+ trajectories (what patterns made
     PTO answers good? how did correct tool routing work?)
5. Each analyst proposes skill patches independently
6. **Patch Consolidator** merges 25 patches hierarchically:
   - Finds prevalent patterns (e.g., 12/15 error analysts identify
     missing scope boundaries)
   - Discards idiosyncratic observations (1 analyst noted a formatting
     edge case)
   - Produces a single comprehensive SKILL.md update
7. PR created with evolved skill + new eval cases
8. Before/after comparison: quality score jumps from 60% to 95%

**Demo narrative**: "Instead of fixing problems one at a time, the
system analyzed 50 trajectories in parallel, found the 4 most common
failure patterns, and produced a comprehensive skill update in 3
minutes. The same analysis would take a human expert hours of log
review."

**Scenario 2: Skill Creation from Scratch**

Starting state: Minimal parametric skill ("You are an HR assistant").
No specific instructions, no scope rules, no tool guidance.

1. Same traffic generation
2. Most responses are poor (agent doesn't know to use tools, hallucinates,
   doesn't decline out-of-scope)
3. Trace2Skill pipeline runs on the full trajectory pool
4. **From trajectory evidence alone**, the system discovers:
   - Which topics the agent's tools can handle (by analyzing T+ patterns)
   - Common failure modes (by analyzing T- root causes)
   - Effective tool-calling sequences (from successful tool chains)
   - Scope boundaries (topics with no successful trajectories)
5. Produces a comprehensive skill from scratch that matches or exceeds
   the human-written one

**Demo narrative**: "We gave the system a blank-slate agent and let it
build its own operational manual from experience. After analyzing 50
interactions, it discovered the scope, learned the tool-calling
patterns, and wrote decline protocols -- all without a human writing a
single prompt instruction."

**Scenario 3: Cross-Model Skill Transfer**

Starting state: Skill evolved by Gemini Flash analyzing its own
trajectories.

1. Apply the same evolved skill to Gemini Pro (different model)
2. Show that quality improves for the larger model too
3. Even apply to a completely different sub-agent (hr_calculator)
   and show transfer

**Demo narrative**: "A skill written by a smaller model improved a
larger model's performance. The operational knowledge in the skill --
scope rules, tool-calling patterns, error prevention -- is
model-agnostic. This means we can evolve skills cheaply with small
models and deploy them with expensive ones."

#### 4. Metrics & Evaluation

| Metric | What It Shows |
|--------|--------------|
| Quality score before/after skill evolution | Direct improvement |
| Patch survival rate (N proposed -> M kept) | Inductive filtering effectiveness |
| Cross-model transfer delta | Skill generalizability |
| Time: parallel vs. sequential | Efficiency of the approach |
| Evolution convergence | How many trajectory rounds until quality plateaus |

#### 5. What Stays the Same

- BigQuery logging and Conversational Analytics
- Traffic Generator
- CI quality gates (Golden Eval + Load Test)
- GitHub integration (PRs, issues for HITL decisions)
- Human-in-the-loop for business/scope decisions
- Production agents (supervisor, policy_agent, hr_calculator)
- A2A architecture and Cloud Run deployment

---

## Implementation Considerations

### Using ADK for the Analyst Fleet

The Error and Success Analysts can be implemented as ADK sub-agents
dispatched via Python's `concurrent.futures` or `asyncio`:

```python
# Conceptual structure
analyst_fleet = []
for trajectory in failed_trajectories:
    analyst = ErrorAnalyst(
        skill=frozen_skill_copy,
        trajectory=trajectory,
        tools=[read_file, compare_output, inspect_tool_calls]
    )
    analyst_fleet.append(analyst)

# Run all analysts in parallel
patches = await asyncio.gather(*[a.analyze() for a in analyst_fleet])

# Hierarchical consolidation
consolidated = await consolidate_patches(patches, batch_size=8)
```

### Skill Format

Following both papers' recommendations and Anthropic's skill framework:

```markdown
# HR Policy Assistant Skill

## Role & Objective
You are a company HR policy assistant. Your sole purpose is to answer
employee questions about company policies using your lookup tools.

## In-Scope Topics
- PTO (paid time off)
- Sick leave
- Remote work
- Expenses
- Benefits
- Holidays
- HR calculations (PTO balance, working days, next holiday)

## Tool Usage Rules
- ALWAYS call lookup_company_policy before answering any policy question
- NEVER answer from parametric knowledge alone
- For calculations, route to hr_calculator
- After receiving tool results, provide specific actionable answers

## Decline Protocol
If a question is NOT about the topics above, politely decline:
"I can help with [topics]. For [their topic], please contact [team]."

## Known Edge Cases
> (populated by Trace2Skill from trajectory analysis)

## Anti-Patterns
- Never fabricate policy details not returned by tools
- Never provide partial answers when the tool has complete information
- Never route calculation questions to policy_agent
```

### Vertex AI Integration

The evolved SKILL.md can be stored in Vertex AI Prompt Manager for
fast deployment (~30 seconds) without full agent redeployment (~11
minutes). The existing `deploy_prompts.yml` workflow already supports
this pattern.

### BigQuery as Trajectory Store

The existing BigQuery `agent_events` table already captures full
agent interaction traces including tool calls, reasoning, and outcomes.
This is exactly the trajectory data Trace2Skill needs. The Quality
Agent's existing `run_quality_report` tool already partitions sessions
by quality verdict -- extending it to export full trajectories for
the analyst fleet is straightforward.

---

## Research Landscape Context

These papers are part of a broader trend in agent self-improvement:

| System | Approach | Key Limitation |
|--------|----------|---------------|
| Voyager (2023) | Accumulate skills through open-ended interaction | Skills remain implicit, no consolidation |
| Reflexion (2023) | Verbal self-reflection on failures | No persistent skill artifacts |
| ReasoningBank (2026) | Store lessons per trajectory, retrieve at inference | Retrieval quality degrades with distribution shift |
| EvoSkill (2026) | Iteratively diagnose failures, validate updates | Sequential editing, order-dependent |
| Memento-Skills (2026) | Stateful markdown skills, incremental updates | Read-write loop, no parallel analysis |
| SkillRL (2026) | Co-evolve skills and model policies via RL | Requires parameter updates |
| **Trace2Skill** | Parallel analysis + hierarchical consolidation | Batch-only, not continuous |
| **AutoSkill** | Online extraction + versioned merging | Shallow analysis, no agentic investigation |

The two papers we analyzed represent the current state-of-the-art for
**training-free, artifact-based** skill evolution -- the approach most
directly applicable to enterprise agent deployments like ours where
model retraining is not practical.

---

## Summary: Why This Matters for the Demo

| Current Demo Story | Evolved Demo Story |
|---|---|
| "We fix agent bugs one at a time" | "Agents analyze their own experience and write their own operational manuals" |
| Reactive: wait for failure, then patch | Proactive: learn from all experience (successes AND failures) |
| Human writes the skill, agent proposes narrow fixes | Agent builds comprehensive skills from trajectory evidence |
| Each fix is independent, may conflict | All lessons consolidated into a coherent, conflict-free skill |
| Skills are flat prompt strings | Skills are structured directories with hierarchical depth |
| Fixes are model-specific | Evolved skills transfer across models and tasks |

The core message shifts from **"agents managing agents"** to **"agents
that learn from experience and continuously improve their own
operational skills"** -- a more compelling and forward-looking narrative
for enterprise AI.

---

## References

1. Ni, J., Liu, Y., Liu, X., Sun, Y., Zhou, M., et al. (2026).
   *Trace2Skill: Distill Trajectory-Local Lessons into Transferable
   Agent Skills*. arXiv:2603.25158.

2. Yang, Y., Li, J., Pan, Q., Zhan, B., Cai, Y., et al. (2026).
   *AutoSkill: Experience-Driven Lifelong Learning via Skill
   Self-Evolution*. arXiv:2603.01145.

3. Anthropic. (2026). *Skills Framework for Claude Code*.

4. Li, J., et al. (2026). *SkillsBench: Benchmarking Agent Skills*.

5. Han, X., et al. (2026). *SWE-Skills-Bench: Are Agent Skills
   Actually Helpful?*
