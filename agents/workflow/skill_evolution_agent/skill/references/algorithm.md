# Skill Evolution Algorithm

## Full Loop (N rounds)

### Setup
1. Create timestamped run directory: `eval/runs/YYYY-MM-DD_HHMMSS_evolution/`
2. Snapshot current skills to run directory as "initial" for comparison and rollback

### For each round R (1..N):

#### Phase 1: Baseline Traffic + Scoring
1. Run multi-turn traffic generator against current skill version
   - Full: 205 questions, ~15-20 min runtime
   - Quick: 22 questions, ~3 min runtime (use for iteration/validation)
   - Concurrency: 10 parallel conversations
   - Max turns: 4 per conversation

2. Score with SDK scorer (`score_conversations.py`):
     - Tag turns with quality labels
     - Sample 100 trajectories from BigQuery trace logs
     - Score using ground-truth-aware judge on 5 dimensions
     - Extract correction boundaries from multi-turn conversations
     - Output: `quality_report.json` with meaningful_rate, unhelpful_rate

3. Print baseline metrics:
   - Total sessions
   - Meaningful rate (target improvement per round)
   - Unhelpful rate
   - Off-topic, error, incomplete counts

#### Phase 2: T+/T- Partition
1. Partition sessions into T+ (success) and T- (failure):
   - `meaningful` or `declined` → T+
   - `unhelpful` or `partial` → T-
   - **Parroting override**: If a session scored `meaningful` but has
     a sub-trajectory with `outcome == "parroted"`, reclassify it as
     T-. A parroted recovery means the agent echoed the user's
     correction without re-querying a tool — the user did the agent's
     work, so it's not a genuine success.

2. Evolution gate: If T- count < MIN_FAILURES (default 30):
   - STOP the loop — do not evolve, do not snapshot a duplicate
     version, do not run further rounds
   - Rationale: Sparse patch sets produce weaker consolidated skills
   - Proceed directly to Cleanup (comparison table + archive)
3. Otherwise proceed to Phase 3

#### Phase 3: Bottleneck Detection
1. Sample failed conversation traces
2. LLM classifier analyzes each failure:
   - Routing failure: supervisor sent query to wrong agent
   - Skill failure: policy_agent has skill gap or anti-pattern
   - Tool failure: tool unavailable or returned error
   - Architecture failure: multi-hop reasoning required, context overflow, etc.
3. Count failures by source agent
4. Decide which agent(s) to evolve:
   - If >70% skill failures: evolve policy_agent skill
   - If >70% routing failures: evolve supervisor skill
   - If mixed: evolve both (future work)

#### Phase 4: Evolution
1. Run `evolve()` with configuration:
   - `--agentic`: Multi-turn error analysts (mandatory)
   - `--score-patches`: Analyst self-scoring for prevalence threshold
   - `--model gemini-2.5-pro`: Consolidation model
   - `--max-workers 10`: Parallel analyst fleet
   - `--candidates N`: Generate N consolidated candidates (best-of-N selection)
   - `--candidates-dir`: Output directory for candidates

2. Evolution substeps:
   - Analyst fleet: Parallel error/success analysts generate patches from trajectories
     - Error analysts receive T- trajectories with execution sub-trajectories
       formatted as `[-]` (wrong), `[+]` (recovered), `[~]` (parroted) segments
     - Root cause categories: KEYWORD_GAP, MISSING_RULE, AMBIGUITY,
       SCOPE_GAP, HALLUCINATION, PARROTING, CORRECTION_IGNORE
     - PARROTING: Agent accepted user's correction without re-querying
       a tool. The skill should instruct independent verification.
     - Success analysts receive T+ trajectories; sessions with parroted
       sub-trajectories are excluded (output "NO_PATCH: parroted recovery")
   - Patch scoring: Analysts score their own patches (0-10 relevance scale)
   - Prevalence filtering: Retain patches appearing in 3+ independent outputs
   - Consolidation: Generate N candidates from filtered patch pool
   - If N=1: Use single candidate
   - If N>1: Best-of-N selection (see Phase 4.3)

3. Best-of-N selection (if candidates > 1):
   - For each candidate C (1..N):
     - Deploy candidate skill to target agent
     - Run quick traffic (22 questions, ~3 min)
     - Score with SDK scorer
     - Record meaningful_rate(C)
   - Select candidate with highest meaningful_rate
   - Compare against incumbent V(R-1):
     - If regression (meaningful_rate drops): reject candidate, keep V(R-1)
     - Otherwise: accept candidate as V(R)

4. Snapshot evolved skill as V(R) in run directory

5. Optional: Compaction pass
   - If skill size > MAX_SKILL_CHARS (default 25000):
     - Run LLM-based distillation
     - Preserve tool rules, keyword mappings, anti-patterns
     - Target: 10K-15K chars
     - Validate: Score compacted skill, reject if regression

#### Phase 5: Validation Traffic
1. Deploy evolved skill V(R)
2. Run full traffic (205 questions) or quick traffic (22 questions) based on mode
3. Score with SDK scorer
4. Report delta from V(R-1):
   - Meaningful rate change
   - Unhelpful rate change
   - Per-dimension breakdown

### Cleanup
1. Print comparison table (all versions):
   ```
   | Version | Meaningful | Unhelpful | Delta | Elapsed Time |
   |---------|-----------|-----------|-------|--------------|
   | initial | 60.0%     | 35.0%     | —     | 15m 32s      |
   | v1      | 94.0%     | 4.0%      | +34.0pp | 12m 18s    |
   | v2      | 98.0%     | 1.0%      | +4.0pp  | 11m 45s    |
   ```

2. Archive run directory with all artifacts:
   - Skill snapshots (initial, v1, v2, ...)
   - Traffic results (results.json per version)
   - Quality reports (quality_report.json per version)
   - Analyst patches and candidate skills (if --candidates-dir used)

---

## Configuration Defaults

| Parameter | Default | Purpose |
|-----------|---------|---------|
| ROUNDS | 2 | Two-round strategy (initial→v1→v2) |
| CANDIDATES | 3 | Best-of-N selection (optimal cost/quality) |
| MIN_FAILURES | 30 | Evolution gate threshold |
| CONCURRENCY | 10 | Parallel conversation count |
| MAX_TURNS | 4 | Max turns per conversation |
| MAX_SKILL_CHARS | 25000 | Triggers compaction pass |
| AGENTIC | true | Multi-turn error analysts (mandatory) |
| TRAJECTORY_SAMPLES | 100 | Traces sampled from BigQuery |
| QUICK_QUESTIONS | 22 | Quick validation set size |
| FULL_QUESTIONS | 205 | Full evaluation set size |

---

## Key Decision Points

### Why Two Rounds Minimum?
- V1 discovers the failure landscape: weak patches (+1.5pp gain) but identifies root causes
- V2 writes strong fixes: builds on V1 analysis (+33.1pp gain)
- Single-round evolution misses compounding insight from V1 error analysis

### Why Best-of-3?
- Consolidation has 6.9pp variance across identical inputs (Trace2Skill finding)
- Cost: 3x consolidation (cheap, ~30s each) vs 1x analyst fleet (expensive, ~10min)
- Single candidate: 70% success rate
- Best-of-3: 97% success rate
- Optimal trade-off for production systems

### Why Always Agentic?
- Multi-turn investigation outperforms single-pass by 6.8pp (Trace2Skill)
- Biggest gains on complex failures (hallucination, refusal)
- Error analysts need to explore trajectories, test hypotheses
- Marginal cost is low (2-3 LLM calls vs 1), reliability gain is large

### Why Template-Guided for V2+?
- Sequential consolidation compounds errors, produces layout drift
- Use V1 as structural blueprint for V2: preserves sections, prevents bloat
- Improves consistency across rounds without constraining content

### When to Skip Evolution?
- If failures < 30: sparse patch sets produce weaker skills
- Better to accumulate more trajectories and evolve in next round
- Prevents thrashing on noise

### Why V0.1 Adds Correction Verification

The V0 baseline skill is deliberately bare-minimum:
```
You are a helpful assistant that answers employee questions.
Answer based on your knowledge. Be brief.
```

V0.1 adds a single paragraph about correction handling:
```
When a user corrects you or disputes your answer, do not simply
accept their correction. Use your available tools to verify the
claim independently, then respond with what you find.
```

This small change matters because it creates the signal the evolution
pipeline needs. Without it, when a user corrects the agent, the agent
just echoes "you're right" (parroting) — producing a conversation that
*looks* correct in the final response but where the agent added no
value. With the correction verification instruction, the agent
re-queries its tools, producing an execution trace that shows whether
the recovery was genuine (tool call after correction) or parroted
(no tool call).

The evolution pipeline uses this signal in two ways:
1. **T+/T- partition**: Parroted recoveries are reclassified from T+
   to T-, so the error analyst examines them instead of the success
   analyst trying to extract a non-existent success pattern.
2. **Sub-trajectory rendering**: Parroted segments are marked `[~]`
   in the formatted trajectory, giving the error analyst explicit
   evidence of what went wrong — the agent accepted the correction
   without verification.

Without V0.1's correction verification line, the evolution pipeline
operates on noisier data: parroted sessions contaminate T+ and the
algorithm tries to learn from cases where the user did the agent's
work.
