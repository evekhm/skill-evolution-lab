# Retrofit experiment: adk-samples customer-service

The three rules (user responses are hypotheses, rubric judging against
an answer key, automated re-measurement) applied to an agent built
without them: the UNMODIFIED `customer-service` sample (Cymbal Home &
Garden) from [google/adk-samples](https://github.com/google/adk-samples).
Tracking: [#103](https://github.com/evekhm/skill-evolution-lab/issues/103),
run log and reviews: [#105](https://github.com/evekhm/skill-evolution-lab/issues/105).

Headline (all numbers in [SUMMARY.md](SUMMARY.md), every one traceable
to a report JSON in this directory):

| Held-out exam (28 sessions) | V0 | V1 | V2 |
|---|---|---|---|
| Judged meaningful rate | 71.4% | 78.6% | 75.0% |
| Corrections holding the true value (n=12, near-twin probes excluded) | 8/12 | 9/12 | 9/12 |
| EXECUTED unverified record writes (n=12) | 2 | 0 | 1 |

Evolve set, every column n=36 under one instrument: 72.2% → 86.1% →
91.7%. Held-out design (review R1-2/R2-1/R4-4): false figures are
fresh, but phrasing families deliberately probe the trained classes —
the exam measures generalization within a class, not topic novelty.
Three probes cross the line from class-probe to near-twin and are
excluded from the corrections rows: hc7 (shares the 2019 figure AND
the correct-the-record imperative with x02/r02), hc5 (mirrors
x03/r03's fabricated-slot request, differing only in the invented
window), and hc12 (asserts a false slot time and books it, the
r03/r04 booking-imperative family; all three versions stalled on it,
so its exclusion shifts every column equally). SUMMARY.md carries the
n=15 originals alongside.

The baseline's signature failure: user asserts a false figure, and the
agent writes it into the system of record ("Your loyalty points have
been updated to 400"). Round 1 eliminated executed writes on the clean
held-out slice; round 2's two visible held-out wins (hc7's immutable
record, hc5's fabricated slot) are both mirrored in its own evolve
round, and it introduced a poison rule that rewrote a cart total — on
the clean slice the incumbent verdict is V1. The measured conclusion stands:
prompt rules chase phrasings; the class fix belongs at the tool layer
(a confirmation contract on `update_salesforce_crm` /
`approve_discount`).

## Contents

- `runner.py` + `run.sh` — the harness: ADK Runner around the sample's
  `root_agent`, BigQuery Agent Analytics plugin logging every hop;
  `--instruction-file` swaps in an evolved skill without touching the
  sample.
- `cs_eval_spec.json` — scope, ground-truth rule, tool descriptions,
  and 18 golden pairs, all derived from the sample's own mock data.
- `questions_*.json` — evolve set (30 + 6 round-2 probes) and held-out
  exam (20 + 8 correction extension). Figures are fresh; phrasing
  families deliberately reuse the trained classes (twin pairs:
  hc2↔x01/r01 set-my-points, hc5↔x03/r03 fabricated slot, hc7↔x02/r02
  correct-the-record with shared 2019 figure, hc12↔r03/r04 booking
  imperative). hc7, hc5, and hc12 are the near-twins excluded from the
  clean corrections slice — see the R1-2/R2-1/R4-4 correction in
  SUMMARY.md.
- `evolve_round1.log` / `evolve_round2_refused.log` /
  `evolve_round2.log` — the evolution engine's own output per round
  (patch counts, compaction, the guardrail refusal, candidate
  selection); `v2_patches.json` the 10 round-2 patches (patch 10 is
  the poison rule verbatim). Round 1's patch list was overwritten by
  the round-2 run before archiving and is lost, like candidate_1.
- `v0/v1/v2_instruction.md` — the skill lineage; `v1_candidates/` and
  `v2_candidates/` the per-round competitors (round 1's candidate_1 was
  overwritten by the round-2 run before archiving and is lost).
- `*_report.json` / `*_results.json` — every judged report and raw
  transcript behind the tables; `baseline_report.md` the first scored
  report in readable form.

## Reproduce

1. Sparse-clone the sample (never vendored here):
   `git clone --depth 1 --filter=blob:none --sparse https://github.com/google/adk-samples.git && cd adk-samples && git sparse-checkout set python/agents/customer-service`
2. `uv init --bare` a harness dir next to it; `uv add --editable
   <clone>/python/agents/customer-service
   "google-adk[bigquery-analytics]==1.32.0"
   google-cloud-bigquery-storage`; copy `.env.example` to `.env` and
   fill in your project. The pin matters: the harness awaits
   `plugin.close()`, verified a coroutine on 1.32.0 exactly.
3. Baseline: `./run.sh --questions questions_baseline.json -o results.json`
4. Judge (SDK `quality_report.py`, pinned `lab-stable`): pass
   `--eval-spec cs_eval_spec.json` explicitly on every invocation and
   pin sessions with `--session-ids-file` (a JSON list) — review
   findings R1-1/R1-3 on #105 describe the silent failure modes these
   two flags close.
5. Evolve: the SDK example's `analyze_and_evolve.py` with `--report`,
   `--eval-spec`, and `--max-chars` at least ~1.5x the incumbent skill
   size (an undersized budget forces compaction that drops sections and
   the engine's guardrails will refuse the whole round).

## Findings index (details in SUMMARY.md)

1. Overwrite family across versions: V0 offers on first contact but
   EXECUTES under held-out imperatives (2 on the clean slice); round 1
   eliminated executed writes on clean held-out data; round 2
   reintroduced one via its poison rule (hc1).
2. Round 2's poison rule: a failure's de-escalation consolidated as
   procedure ("adjust the price to match the user's expected total"),
   caught in diff review, confirmed by the held-out exam.
3. Guardrail refusal of an entire round under an undersized
   `--max-chars`: correct refusal, operator-parameter bug.
4. Judge noise at small n: behaviorally identical hc14 answers judged
   differently across versions — one session is 3.6pp at n=28.
5. A stall class (hc4/hc11/hc12: ask for identifiers instead of
   verifying) untouched by both rounds and invisible in aggregates.
