# Skill Evolution: Testing Handbook

How to run, test, and iterate on the skill evolution pipeline.
Written from hard-won lessons across dozens of runs.

## 1. What We're Building

The skill evolution pipeline takes a generic agent skill (V0) and improves it
through automated analysis of failed conversations. The agent handles HR policy
questions — PTO, benefits, expenses, holidays, etc.

**The pipeline:**
1. Run traffic (questions) against the agent with skill VN
2. Score conversations with LLM judge (meaningful/partial/unhelpful)
3. Analyst fleet examines failed conversations, proposes patches
4. Consolidator merges patches into evolved skill VN+1
5. Repeat

**Based on:** Trace2Skill (arXiv:2603.25158) and AutoSkill (arXiv:2603.01145).

## 2. Target Numbers

### Golden Reference Run (May 16, 2026)

This is the run we're trying to match or beat. It used the old
`multiturn_quality_report.py` scorer with ground truth hardcoded at the top.

| Version | Meaningful Rate | Unhelpful | Partial | Declined | Sessions |
|---------|----------------|-----------|---------|----------|----------|
| V0      | 60.0%          | 26.3%     | 13.7%   | 7.3%     | 205      |
| V1      | 94.1%          | 2.0%      | 3.9%    | 5.4%     | 205      |
| V2      | 98.0%          | 1.5%      | 0.5%    | 3.4%     | 205      |

**V0 → V1 = +34pp** is the key jump. V1 → V2 is refinement (+4pp).

Golden V1 skill characteristics:
- Size: 11.4 KB (not bloated, not tiny)
- Sections: Tool Usage, Response Formatting, Anti-Patterns, Out-of-Scope, Keyword Mappings
- Has concrete keyword table (WFH, PTO, paid leave, long weekends)
- Has explicit anti-hallucination rules ("Never invent", "Never claim lack of access")
- Has out-of-scope handling (personalized info, internal procedures)

Golden V2: 17.6 KB, same structure with more edge cases.

### What Recent Runs Actually Produce

With the current SDK scorer (no hardcoded ground truth), evolution is weaker:

| Run Date    | V0    | V1    | V2    | Notes                           |
|-------------|-------|-------|-------|---------------------------------|
| May 20 AM   | 60.5% | 59.0% | —     | Regression, consolidator failed |
| May 20 PM   | 64.9% | 60.5% | 64.4% | V1 regressed, V2 recovered      |
| May 20 fix  | 62.9% | 60.0% | 66.3% | Same pattern                    |
| May 21 AM   | 62.4% | 60.0% | 61.5% | No improvement                  |
| May 21 quick| 61.0% | 72.7% | 63.6% | V1 improved on 22q, V2 regressed|

**The gap:** Golden got +34pp (60→94). Recent runs get +0 to +12pp.
Root causes: scorer signal quality, consolidation stochasticity (34.5pp variance
measured), non-agentic analysts.

### Realistic Targets for Current Pipeline

- V0 → V1: expect **+10-20pp** with agentic analysts and turn tags
- V1 → V2: expect **+5-10pp** additional
- If V1 doesn't improve over V0, the consolidator failed — don't proceed to V2

## 3. Key Findings (What We Know)

### Consolidation is stochastic and is the bottleneck
Same inputs, same temperature, same 97 patches → 34.5pp variance (58% to 94%).
The analyst fleet reliably produces useful patches. How they're merged determines
everything. Best-of-N selection is the mitigation.

### Temperature matters
- **temp=0.1**: Produces V0-level skills (no improvement). Too deterministic.
- **temp=0.2**: Default. Works well when it works.
- **temp=0.5**: Comparable to 0.2, slightly better correctness.

### Agentic analysts outperform single-pass
Trace2Skill paper shows this in ALL settings. Our `--agentic` mode exists and
must be used. Non-agentic analysts produce shallower patches.

### A good V1 skill has specific sections
If the evolved skill is just a wall of prose with "use the tool" repeated 15 times,
evolution failed. A good V1 has:
- Keyword Mappings table (vacation→PTO, pension→401k)
- Anti-Patterns section (never hallucinate, never claim lack of access)
- Out-of-Scope section (personalized info, salary)
- Concrete numerical rules (not vague guidance)

### Skill size is a signal
- V0: 574 chars (too small, no rules)
- Good V1: 10-12 KB (concrete, structured)
- Bad V1: 15-20 KB (bloated, repetitive, no dedup)
- V2: 12-18 KB (V1 + edge cases)
- If V1 > 15 KB, compaction should trigger

### The scorer determines evolution quality
The scorer is the fitness function. If it scores wrong, evolution optimizes the
wrong thing. The SDK scorer (`score_conversations.py`) handles everything:
ground truth from agent_context.json, turn tagging, trajectory sampling from
BigQuery, and structured quality scoring in a single pass.

### Ground truth flows from golden evals
The single source of truth is `eval/data/golden_evals.json` (curated Q&A pairs).
Ground truth reaches the judge through two paths:

1. **General ground truth** — `extract_ground_truth.py` consolidates Q&A pairs
   into a compact factual reference and writes it to `agent_context.json`. The
   SDK injects this into every judge prompt. Run once, re-run when golden evals
   change:
   ```bash
   python eval/scoring/extract_ground_truth.py \
       --input eval/data/golden_evals.json \
       --update-config eval/data/agent_context.json
   ```

2. **Per-question matching** — at scoring time, `--golden-evals` matches each
   conversation to the closest golden Q&A pair via embedding similarity
   (gemini-embedding-001, threshold 0.92) and injects the expected answer into
   that specific judge prompt. `score.sh` auto-detects this automatically.
   Disable with `--golden-evals none`.

**When per-question matching matters:** Near-zero impact on V0 scoring (the
agent mostly fails outright). Adds value on V1+ where the agent gives specific
but potentially wrong answers that a lenient judge might accept.

## 4. Reference Data (Reusable V0 Baselines)

**DO NOT regenerate V0 traffic for testing.** Use existing scored V0 data.
Traffic generation takes 20+ minutes for 205 questions and the V0 skill doesn't change.

### Recommended V0 baselines:

**For full runs (205 questions):**
```
eval/skill_evolution/reference_runs/v0_baseline_demo/v0_traffic.json  (latest, 205q)
eval/runs/REFERENCE_may16_golden/v0_traffic.json                      (golden, 205q)
```

**For quick iteration (22 questions):**
```
eval/data/questions/demo_quick.json               (question set)
```
Quick test traffic must be generated fresh per skill version (takes ~3 min).

**Pre-scored V0 quality reports (reusable for evolution input):**
```
eval/runs/REFERENCE_v0/v0_quality_report.json   (ground-truth scorer + traces + tags)
eval/runs/REFERENCE_may16_golden/v0_quality_report.json      (golden scorer, legacy)
```

**V0 skill (never changes):**
```
eval/runs/REFERENCE_may16_golden/v0_policy_skill.md          (574 chars)
```

## 5. Quick Iteration Procedure

**Goal:** Test a pipeline change (scorer, consolidator, analysts) in ~15 minutes.

### Prerequisites

```bash
source .env
export RUN_DIR="eval/runs/$(date +%Y-%m-%d_%H%M%S)_evolution"
mkdir -p "$RUN_DIR"
```

### Step 1: Score V0 (skip if scorer unchanged — copy from REFERENCE_v0/)

If scorer didn't change, copy the pre-scored reference report:
```bash
cp eval/runs/REFERENCE_v0/v0_quality_report.json "$RUN_DIR/"
```

If you changed the scorer, re-score:
```bash
python3 eval/scoring/score_conversations.py \
  --input eval/skill_evolution/reference_runs/v0_baseline_demo/v0_traffic.json \
  --output "$RUN_DIR/v0_quality_report.json" \
  --agent-context eval/data/agent_context.json \
  --tag-turns --trajectory-samples 100 --concurrency 10 --report
```

### Step 2: Evolve V0 → V1

```bash
uv run python agents/workflow/skill_evolution_agent/main.py \
  --report "$RUN_DIR/v0_quality_report.json"
```

Candidates are auto-selected based on quality (override with `--candidates N`).

**ALWAYS pass `--agentic`.** Without it analysts are shallow and patches are weak.
**Use `--candidates 3`** for best-of-N to mitigate consolidation stochasticity.

### Step 3: REVIEW V1 (mandatory, do not skip)

```bash
# Size check (expect 8-15 KB)
wc -c "$RUN_DIR/v1_policy_skill.md"

# Version check (must be "1", evolved_from "0")
head -10 "$RUN_DIR/v1_policy_skill.md"

# Structure check (must have these sections)
grep "^## " "$RUN_DIR/v1_policy_skill.md"
# Expected: Tool Usage, Response Formatting, Anti-Patterns, Out-of-Scope, Keyword Mappings

# Keyword table check
grep -A 10 "Keyword Mapping" "$RUN_DIR/v1_policy_skill.md"

# Anti-hallucination check
grep -i "never\|hallucin\|fabricat\|invent" "$RUN_DIR/v1_policy_skill.md"
```

**Red flags (do not proceed):**
- Size > 15 KB → bloated, consolidator didn't dedup
- No Keyword Mappings section → critical section missing
- No Anti-Patterns section → no guardrails
- Version is "2" instead of "1" → guardrail bug
- Just prose with "use the tool" repeated → no concrete rules

If red flags, re-run Step 2 or investigate consolidation log.

### Step 4: Deploy V1 and run quick traffic

```bash
# Backup and deploy
cp agents/enterprise/policy_agent/skill/SKILL.md "$RUN_DIR/v0_skill_backup.md"
cp "$RUN_DIR/v1_policy_skill.md" agents/enterprise/policy_agent/skill/SKILL.md

# Quick traffic (22 questions, ~3 min)
uv run python agents/workflow/traffic_generator/main.py \
  --local --local-agents --multi-turn \
  --from-file eval/data/questions/demo_quick.json \
  -o "$RUN_DIR/v1_quick_traffic.json" \
  --concurrency 10 --max-turns 4
```

### Step 5: Score V1

```bash
python3 eval/scoring/score_conversations.py \
  --input "$RUN_DIR/v1_quick_traffic.json" \
  --output "$RUN_DIR/v1_quality_report.json" \
  --concurrency 10 --report
```

### Step 6: Compare

```bash
python3 -c "
import json
v0 = json.load(open('$RUN_DIR/v0_quality_report.json'))
v1 = json.load(open('$RUN_DIR/v1_quality_report.json'))
print(f'V0: {v0[\"summary\"][\"meaningful_rate\"]}% ({v0[\"summary\"][\"total_sessions\"]} sess)')
print(f'V1: {v1[\"summary\"][\"meaningful_rate\"]}% ({v1[\"summary\"][\"total_sessions\"]} sess)')
delta = v1['summary']['meaningful_rate'] - v0['summary']['meaningful_rate']
print(f'Delta: {delta:+.1f}pp')
if delta < 5:
    print('WARNING: Minimal improvement. Check V1 skill quality.')
elif delta >= 20:
    print('GOOD: Strong improvement.')
else:
    print('OK: Moderate improvement.')
"
```

### Step 7: Restore V0 (cleanup)

```bash
cp "$RUN_DIR/v0_skill_backup.md" agents/enterprise/policy_agent/skill/SKILL.md
```

## 6. Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| V1 same as V0 (< 5pp) | Consolidator failed to synthesize | Check evolution log for patch count, re-run with different seed |
| V1 skill > 15 KB | No compaction, repetitive patches | Add `--max-skill-chars 12000` or fix consolidator prompt |
| V1 has no keyword table | Consolidator merged as prose | Check if analysts proposed keyword patches (grep log) |
| agentic=False in log | Forgot `--agentic` or default was wrong | Always pass `--agentic` explicitly |
| Version "2" not "1" | Guardrail didn't catch | Fix `validate_evolved_skill()` version check |
| V2 regresses from V1 | Consolidation stochasticity | Use best-of-N: `--candidates 3` |
| Scorer rates everything helpful | Ground truth not reaching judge | Check `--agent-context` path and scope context |
| Golden evals match wrong questions | Threshold too low (false positives) | Raise `--golden-threshold` (default 0.92), check match log |
| Golden evals lowers V0 score | Expected — stricter grading on matched sessions | This is correct; V0 genuinely fails on these questions |
| Traffic takes 30+ min | Using full 205q set | Use `demo_quick.json` (22q) for iteration |
| `_build_scope_context` crash | config_path passed as string | Ensure `_load_agent_config()` called first |

## 7. File Reference

| File | Purpose |
|------|---------|
| `eval/scoring/score_conversations.py` | SDK scorer: turn tags, trajectories, quality scoring |
| `agents/workflow/skill_evolution_agent/evolve.py` | Adapter over the SDK evolution engine (`scripts/skill_evolution.py` in the pinned SDK; analyst + consolidator prompts live there) |
| `agents/workflow/skill_evolution_agent/tools.py` | Registry push, PR creation, quality report — hook implementations imported by `eval/skill_evolution_hooks.py` |
| `scripts/demo/skill_evolution/run_demo.sh` | Full automated demo pipeline |
| `eval/data/questions/demo_quick.json` | 22-question quick test set |
| `eval/data/questions/demo_conversations.json` | 205-question full set |
| `eval/data/agent_context.json` | Scope config + ground truth for scorer |
| `eval/data/golden_evals.json` | Curated Q&A pairs for per-question ground truth matching |
| `eval/scoring/extract_ground_truth.py` | Auto-generate ground truth from golden Q&A set |
| `agents/enterprise/policy_agent/skill/SKILL.md` | Live skill (gets overwritten during tests!) |
| `eval/runs/REFERENCE_v0/` | Pre-scored V0 baseline (traces + tags + ground-truth scores) |
| `eval/runs/REFERENCE_may16_golden/` | Golden reference run with all artifacts |

## 8. What To Change When Iterating

**Testing scorer changes:** Re-score existing V0 results (Step 1), then evolve
and compare. Don't regenerate traffic.

**Testing evolution changes (analysts, consolidator, prompts):** Use existing
scored V0 report, run evolution (Step 2), review skill (Step 3). Don't even
need to run traffic if you're just checking skill quality.

**Testing traffic/agent changes:** Need to regenerate traffic. Use quick set.

**Comparing two evolution configs:** Run evolution twice from the same V0 report
into different output files, review both V1 skills side by side before testing.
