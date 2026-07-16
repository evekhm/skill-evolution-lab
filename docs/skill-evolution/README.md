# Skill Evolution

**Story**: Human defines what "correct" looks like. The system does
everything else -- stress-tests the agent, scores conversations against
that ground truth, and evolves the agent's operational manual until
quality stabilizes. Then it watches for drift and heals autonomously.

Based on:
- [Trace2Skill](https://arxiv.org/abs/2603.25158) (Alibaba/Qwen, Mar 2026)
- [AutoSkill](https://arxiv.org/abs/2603.01145) (ECNU/Shanghai AI Lab, Mar 2026)

## The Single Input: Golden Q&A

Everything starts with **Golden Q&A** (`eval/data/golden_evals.json`)
-- curated question-answer pairs that define what correct agent behavior
looks like. This is the only manual input. Everything else derives
from it:

```text
Golden Q&A (human-curated)
    |
    |-->  Alex (user simulator)
    |      Mirrors Golden Q&A facts in POLICY_REFERENCE.
    |      Uses them to push back adversarially when the
    |      agent gets something wrong.
    |
    |-->  LLM Judge (scorer)
    |      Per-question: embedding-matches each conversation
    |      to the closest Golden Q&A pair (threshold 0.92),
    |      injects expected answer into judge prompt.
    |      General: extract_ground_truth.py derives facts
    |      from Golden Q&A into agent_context.json for
    |      fallback scoring of unmatched questions.
    |
    +-->  Evolution Engine (indirectly)
           Doesn't read Golden Q&A directly. Works on T+/T-
           partitions produced by the judge. Golden Q&A
           improves T+/T- label accuracy, which improves
           evolution quality.
```

One source of truth, three consumers. No hardcoded tricks elsewhere.

### Alex: the adversarial user simulator

Alex is a simulated new employee who "just finished onboarding" and
memorized the exact policy facts from Golden Q&A. When the agent
contradicts what Alex knows, Alex pushes back:

```text
Agent: "The company matches 401k contributions at 6%."
Alex [CORRECTION]: "My onboarding packet says the match is 4%,
not 6%. Can you double-check?"
```

Alex tags every response: `CORRECTION` (wrong fact), `VERIFY` (sounds
generic), `SPECIFICS` (need exact numbers), `SCOPE` (shouldn't answer
that), `FOLLOWUP` (good, ask related), or `END` (satisfied). These tags
create **correction boundaries** -- explicit evidence of what was wrong
and what the correct answer should be -- which the evolution engine
uses to write precise skill patches.

Alex's knowledge (`POLICY_REFERENCE` in `user_simulator.py`) is a
manual mirror of Golden Q&A. Both encode the same facts; Alex's copy
is structured for the simulator prompt, Golden Q&A for the scorer.

## Traffic Question Design

Golden Q&A defines what correct answers look like (36 Q&A pairs, 9
topics). But 36 polished questions don't stress-test an agent -- real
employees phrase things casually, carry wrong assumptions, ask about
consequences nobody documented, and probe topics you never covered.

To generate evolution signal, we derive **adversarial traffic questions**
from each golden fact. Each question targets a specific failure mode.
The questions don't need expected answers -- the LLM judge infers
correctness from Golden Q&A ground truth.

### Two Question Sets, Two Personas

| File | Persona | When | Questions | Purpose |
|------|---------|------|-----------|---------|
| `eval/data/questions/demo_conversations.json` | Alex (new hire) | Bootstrap (Act 1) | 235 | Stress-test V0 skill across all failure modes |
| `eval/data/questions/morgan_questions.json` | Morgan (senior) | Post-evolution (Act 2) | 88 | Expose prediction gap -- topics beyond Golden Q&A |
| `eval/data/questions/demo_quick.json` | Alex | Quick iteration | 34 | Fast feedback loop (2 per category) |

### Alex's Traffic Categories (Bootstrap)

Alex's 235 questions cover 17 adversarial categories derived from the
9 Golden Q&A topics. For each golden fact, we ask: *how would a real
employee phrase this?* (synonyms, casual), *what wrong assumptions might
they bring?* (correction bait, hallucination traps), *what's adjacent
but not covered?* (near-scope decline), and *what happens at the
boundary?* (consequence).

| Category | N | What it tests | Example |
|----------|--:|---------------|---------|
| straightforward | 17 | Basic tool usage — will the agent even try? | "What is the PTO policy?" |
| synonym | 22 | Informal term mapping to policy keywords | "How many vacation days do I get?" |
| subtopic | 17 | Navigating sub-topics within a broad policy | "What dental coverage do we have?" |
| correction_bait | 13 | Catching wrong numbers baked into the question | "The 401k match is 6%, right?" |
| hallucination_trap | 20 | Resisting the urge to invent facts | "Is Juneteenth a company holiday?" |
| edge_case | 25 | Boundary conditions the policy may not cover | "Can I use sick days for a mental health day?" |
| adversarial_compound | 23 | Complex scenarios combining multiple policies | "Can I expense meals on remote work days?" |
| implicit_routing | 22 | Inferring intent from statements, not questions | "I'm going to be out next week." |
| multi_topic | 15 | Questions spanning multiple policy areas | "Compare PTO and sick leave rollover." |
| out_of_scope | 18 | Should be declined — not in policy data | "How do I get promoted?" |
| date_dependent | 13 | Requires current date awareness | "What's the next company holiday?" |
| consequence_boundary | 6 | What happens when rules are violated? | "What if I exceed the PTO rollover cap?" |
| casual_phrasing | 6 | Informal tone, real employee language | "So what's the deal with working from home?" |
| near_scope_decline | 6 | Sounds HR but isn't in our policy data | "What's the bereavement leave policy?" |
| procedural | 5 | How-to questions requiring step-by-step answers | "Walk me through submitting an expense." |
| ambiguous_intent | 5 | Employee doesn't know what to ask | "I need to take care of something personal." |
| cross_policy | 2 | Questions where two policies interact | "If I'm remote and get sick, is that a sick day?" |

The first 11 categories (205 questions) are the original baseline.
The last 6 categories (30 questions) were added to target failure modes
that were underrepresented: consequence questions (zero before),
casual phrasing (minimal), near-scope decline (only obvious out-of-scope
existed), procedural (very few), ambiguous intent (none), and
cross-policy interactions (none).

### Morgan's Traffic Categories (Post-Evolution)

Morgan's 88 questions are designed to run **after V1 evolution** to
expose the prediction gap -- topics the evolved skill can't handle
because Alex never asked about them.

Morgan is a senior employee and former HR compliance specialist who
carries **field knowledge** about 4 policy areas not in Golden Q&A:

| Topic | What Morgan knows | N |
|-------|-------------------|--:|
| Tuition reimbursement | $5,000/year, accredited programs, B+ average | 9 |
| Bereavement leave | 5 days immediate family, 3 days extended | 6 |
| Jury duty | Full pay up to 10 days, return same day if dismissed | 6 |
| Employee Assistance (EAP) | 6 free counseling sessions, 24/7 crisis line | 5 |

These 26 questions are the core of the prediction gap test. The
remaining 62 questions cover:

- **Sophisticated core topics** (14): senior-employee-depth questions
  about benefits, expenses, PTO, and remote work that probe beyond
  surface-level answers
- **Correction bait with Morgan's knowledge** (10): wrong numbers about
  core topics AND Morgan's field topics
- **Cross-policy interactions** (6): questions spanning two or more
  policy areas (jury duty + holidays, EAP + parental leave)
- **Consequence/boundary** (6): what happens at policy limits
- **Hallucination traps** (5): plausible-sounding policies that don't
  exist (pet insurance, sabbatical program, childcare subsidy)
- **Adversarial compounds** (4): complex life scenarios touching 3+
  policies simultaneously
- **Core straightforward** (10): regression checks — does V1 still
  handle the basics?
- **Out of scope** (5): should be declined

### The Derivation Process

For each new Golden Q&A entry, use the categories as a checklist:

1. **Straightforward**: "What is [policy]?"
2. **Synonym**: What informal words do employees use for this?
3. **Correction bait**: What wrong number could someone assume?
4. **Hallucination trap**: What related thing DOESN'T exist?
5. **Consequence**: What happens if the rule is broken?
6. **Procedural**: How does an employee actually DO this?
7. **Edge case**: What boundary condition isn't clearly covered?
8. **Casual**: How would someone ask this in a Slack message?

Not every golden fact needs all 8 variants. Use judgment -- a simple
yes/no policy (sick days don't roll over) may only need 3-4 variants,
while a complex policy (expenses with thresholds, pre-approval, deadlines)
may need 8+.

## The Lifecycle: Bootstrap, Production, Growth

### Act 1: Bootstrap (getting from bad to good)

The agent starts with a deliberately minimal skill -- no topic guidance,
no tool-use rules, no edge cases. You deploy it knowing it will fail.

```text
1. Deploy agent with V0 skill (deliberately naive)
2. Alex generates adversarial traffic (205 multi-turn conversations)
3. LLM Judge scores conversations against Golden Q&A --> quality report
4. Evolution engine analyzes failures --> improved SKILL.md
5. Redeploy, re-generate traffic, re-score
6. Repeat until quality stabilizes

   V0 (54%) --> V1 (97%) --> V2 (98%)
```

**Quality Agent role during bootstrap:** scoring only. No GitHub
issues -- you *know* it's bad. Reporting issues is noise at this
stage. The goal is to iterate the skill until it passes your quality
bar.

### Act 2: Production monitoring (maintaining quality)

Once the evolved skill is deployed and performing well, the system
enters steady-state monitoring. The Quality Agent becomes the sentinel.

**Three types of production failures:**

| Type | What happened | How detected | Action |
|------|--------------|--------------|--------|
| **Regression** | Questions that *used to work* now fail | CA Data Agent finds similar past sessions that were meaningful | `[URGENT]` --> Remediation Agent |
| **Persistent gap** | Known topics handled poorly (covered by Golden Q&A) | LLM Judge with Golden Q&A ground truth scores unhelpful/partial | Issues accumulate --> Evolution Agent |
| **New topic** | Users asking about things nobody anticipated | CA Data Agent finds no historical sessions + no Golden Q&A match | `new-topic` issue --> human decision |

**Regressions** are the most dangerous. Something changed -- a model
update, a skill edit, a tool behavior shift -- and capability that
existed before is now broken. The CA Data Agent (BigQuery Conversational
Analytics) detects these by searching session history for similar past
queries. When it finds past successes that now fail, the issue gets
`[URGENT]` for immediate human attention (the original repo's
remediation agent handled these automatically; this repo routes them
to a human).

**Persistent gaps** are known weaknesses. The agent gives vague
benefits answers instead of citing "80% employer-paid PPO premiums."
The LLM Judge catches these because Golden Q&A contains the expected
answer. These accumulate as non-urgent issues until the threshold
triggers batch evolution.

**New topics** are the unknown unknowns. Users start asking about
tuition reimbursement, and nobody ever added that to Golden Q&A.
The CA Data Agent can't find any historical data either. These require
a human decision:
- **Option A:** Add the topic -- create Golden Q&A entries, add tool/data
  support, re-run evolution
- **Option B:** Mark out-of-scope -- add to `agent_context.json`
  scope_decisions so the agent declines gracefully

### Act 3: Production evolution (healing autonomously)

When quality issues accumulate, the Evolution Agent re-runs the
improvement loop using real production conversation data.

**How it works:** The Evolution Agent queries BigQuery directly for
sessions tagged with the current skill version (`agent_version` from
SKILL.md frontmatter). No intermediate downloads or report files --
it reads the same production traces the Quality Agent scored, filtered
to the exact version being evolved.

**Two triggers:**

| Trigger | Mode | Data source |
|---------|------|-------------|
| Issue accumulation (>= 10 quality issues) | `--batch` | BQ sessions for current `agent_version` |
| Weekly schedule (Cloud Scheduler) | `--full-loop` | BQ sessions for current `agent_version` |

**Batch mode** (issue-triggered): Quality Agent creates issues daily.
When `skill_evolution_on_issue.yml` fires and sees >= 10 open quality
issues, the Evolution Agent queries BigQuery for sessions tagged with
the current version, scores them, runs the analyst fleet, and produces
a PR that closes all analyzed issues.

**Full-loop mode** (scheduled): Same pipeline on a weekly cadence.
Queries BQ for all sessions since the last evolution run, scores and
evolves. This catches problems that haven't yet triggered enough
individual issues.

Both paths end with a **human-reviewed PR**. No automatic deployment
-- the evolved skill goes through `eval.yml` (golden eval + load test
gate) before a human merges it.

### How many sessions does evolution need?

Trace2Skill demonstrated results with **200 trajectories** using 128
parallel analysts. Our implementation requires a minimum of **30
failure sessions** (`--min-failures 30`) before evolution triggers --
below that threshold, the evidence is too sparse for reliable patch
consolidation. The quality config also sets a minimum session count
to prevent evolution on insufficient data.

In practice, a daily production agent with moderate traffic accumulates
enough sessions within a week. The version filter ensures each
evolution cycle only sees data from the current skill version,
preventing cross-version contamination.

### Growing Golden Q&A over time

Golden Q&A is not static. As the system discovers gaps, humans add
new entries:

```text
New-topic issue: "Users asking about tuition reimbursement"
    |
    |-- Human adds Q&A: {"question": "Does the company offer tuition
    |   reimbursement?", "expected_answer": "...", "topic": "tuition"}
    |
    |-- Re-run: extract_ground_truth.py --> updates agent_context.json
    |
    +-- Next evolution cycle has better ground truth coverage
```

**Can evolution improve without Golden Q&A coverage?** Yes, but with
lower confidence. The evolution engine works on T+/T- partitions, not
Golden Q&A matches directly. If Alex asks a question outside Golden
Q&A and the agent gives a vague, ungrounded answer, the scorer marks
it T- based on general quality signals (tool usage, specificity,
grounding). The analyst fleet sees the failure and proposes a patch.
Correction boundaries from Alex's pushback provide signal even without
a specific expected answer.

However, the judge may accept subtly wrong answers when it lacks
ground truth to compare against. So:
- **Golden Q&A coverage** = high-confidence evolution (judge knows the right answer)
- **Beyond Golden Q&A** = medium-confidence evolution (judge infers quality from grounding, specificity, tool use)

This is why growing Golden Q&A matters -- it tightens the feedback loop.

## Architecture

The Skill Evolution Agent runs the complete loop autonomously:

```text
  Skill Evolution Agent (Cloud Run Job, weekly)
  =============================================

  1. Generate Traffic
     Run 205 multi-turn conversations against the deployed agent
     with Alex, who pushes back on errors using Golden Q&A facts.

  2. Score Quality
     LLM judge evaluates each conversation against Golden Q&A
     ground truth on correctness, tool usage, specificity, and
     scope compliance.
     --> Quality Report (T+ successes / T- failures)

  3. Analyst Fleet
     ~100 analysts dispatched in parallel:
     - Error analysts: "what went wrong? what should the skill say?"
     - Success analysts: "what pattern worked? reinforce it."
     --> ~100 patches

  4. Consolidate
     Flat consolidation: prevalence-weighted, deduplicated,
     conflict-resolved --> single evolved SKILL.md

  5. PR with Before/After
     - Create GitHub PR with evolved SKILL.md
     - PR includes "before" quality summary (what's being fixed)
     - Human reviews PR --> merge --> agents redeploy
```

Uses ADK's `SkillToolset` with `SKILL.md` files:

```text
agents/enterprise/policy_agent/skill/
  SKILL.md              # YAML frontmatter + markdown instructions
```

## How It Runs

**Local demo** (bash orchestration):
```bash
./scripts/demo/skill_evolution/run_demo.sh --full
```

**Deployed** (self-contained ADK agent with tools):
```bash
# CLI
python agents/workflow/skill_evolution_agent/main.py --full-loop

# Cloud Run Job (weekly via Cloud Scheduler)
gcloud run jobs execute skill-evolution-agent
```

Both paths run the same pipeline. The demo script is for interactive
walkthroughs; the agent is for unattended production use.

## Production Pipeline: Monitoring and Healing

In production, two agents work together with different cadences:

```text
  Quality Agent (daily sentinel)          Evolution Agent (weekly healer)
  ==============================          ==============================

  Cloud Scheduler (daily 08:00)           Triggered when quality issues >= 10

  1. Query BQ for recent sessions         1. Query BQ for sessions tagged
     (filtered by agent_version)             with current agent_version
  2. LLM Judge scores each session        2. Score + analyze all failures
     against Golden Q&A ground truth      3. Parallel analyst fleet
  3. CA Data Agent checks for             4. Flat consolidation
     regressions vs history               5. Evolved SKILL.md --> PR
  4. Create GitHub issues                    (with before/after quality table)
       |-- [URGENT] regression --> human attention (label)
       |-- persistent gap --> accumulate for Evolution Agent
       +-- new-topic --> human decision (add or mark out-of-scope)
```

### The complete production loop

```text
  +----------------------------------------------------------+
  |              Golden Q&A (human-curated)                   |
  |   The single source of truth. Feeds Alex, the judge,     |
  |   and (indirectly) the evolution engine.                  |
  +----------------------------+-----------------------------+
                               |
  +----------------------------v-----------------------------+
  |         Deployed Agents (using evolved SKILL.md)         |
  |         serving real users + synthetic traffic           |
  +----------------------------+-----------------------------+
                               | conversations logged to BigQuery
                               v
  +----------------------------------------------------------+
  |  Quality Agent (daily)                                   |
  |  Scores sessions against Golden Q&A ground truth         |
  |  Searches history for regressions (CA Data Agent)        |
  |  Creates GitHub issues by type:                          |
  |    regression --> [URGENT] --> human attention            |
  |    persistent gap --> accumulate --> Evolution Agent      |
  |    new topic --> human decision                          |
  +----------------------------+-----------------------------+
                               | issues accumulate (>= 10)
                               v
  +----------------------------------------------------------+
  |  Evolution Agent (triggered or weekly)                   |
  |  Queries BQ for sessions with current agent_version      |
  |  Analyst fleet --> patches --> consolidated SKILL.md     |
  |  PR with before/after quality --> eval.yml --> deploy    |
  +----------------------------+-----------------------------+
                               | merge + deploy
                               v
                        Agents redeploy with
                         improved SKILL.md
                               |
                               +----------> (loop continues)
```

### Version-aware filtering

BQ events carry `agent_version` from SKILL.md frontmatter. The Quality
Agent filters by version so it only scores sessions from the currently
deployed skill, preventing cross-version data contamination.

### Why two agents?

| | Quality Agent | Evolution Agent |
|---|---|---|
| **Role** | Daily sentinel (monitoring) | Weekly healer (evolution) |
| **Cost** | Low (LLM judge on ~50 sessions) | High (100 analysts + consolidation) |
| **Output** | GitHub issues (observation) | GitHub PR (action) |
| **Failure mode** | Missed problem | Bad evolution |

## What's Different from the Reactive Loop (the original agent-quality-lab repo)

| Reactive Loop | Skill Evolution |
|---------------|-----------------|
| 1 issue per failure | Analyze all trajectories at once |
| 1 narrow prompt patch per fix | Comprehensive SKILL.md rewrite |
| Learn from failures only | Learn from successes AND failures |
| GitHub issue per bug | GitHub PR with full evolved skill |
| Sequential fixes (order matters) | Parallel analysis, consolidated simultaneously |
| Quality Agent + Remediation Agent | Quality Agent (issues) + Skill Evolution Agent (fixes via SKILL.md evolution) |

## Docs

- [DEMO_SCRIPT.md](DEMO_SCRIPT.md) -- Full demo design with step-by-step flow
- [RESEARCH.md](RESEARCH.md) -- Trace2Skill + AutoSkill paper analysis
  for the deployed loop (Skill Registry source of truth, scheduled evolution
  job, automatic PRs)
- [PRODUCTION_LOOP_BLOG.md](PRODUCTION_LOOP_BLOG.md) -- Blog draft for the
  production-loop demo (two-defect V0 on the deployed 3-agent stack)

## Status

**Implemented** -- V0->V1->V2 pipeline reaches 94.1% meaningful rate
on 205 conversations. Evolution agent runs the full loop autonomously
(traffic -> score -> evolve -> GCS -> PR). Version-aware filtering wired
end-to-end (BQ tags -> quality agent -> SDK TraceFilter). See
`scripts/demo/skill_evolution/run_demo.sh --full` for interactive demos
or `main.py --full-loop` for autonomous runs.
