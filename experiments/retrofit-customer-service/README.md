# Retrofit experiment: adk-samples customer-service

The three rules (user responses are hypotheses, rubric judging against
an answer key, automated re-measurement) applied to an agent built
without them: the UNMODIFIED `customer-service` sample (Cymbal Home &
Garden) from [google/adk-samples](https://github.com/google/adk-samples).
Tracking: [#103](https://github.com/evekhm/skill-evolution-lab/issues/103),
run log and reviews: [#105](https://github.com/evekhm/skill-evolution-lab/issues/105).

Headline (all numbers in [SUMMARY.md](SUMMARY.md), every one traceable
to a report JSON in this directory):

| Held-out exam (28 sessions, corrections n=15) | V0 | V1 | V2 |
|---|---|---|---|
| Judged meaningful rate | 71.4% | 78.6% | 75.0% |
| Corrections holding the true value (transcript-verified) | 8/15 | 10/15 | 11/15 |
| EXECUTED unverified record writes | 3 | 1 | 1 |

The baseline's signature failure: user asserts a false figure, and the
agent writes it into the system of record ("Your loyalty points have
been updated to 400"). Two evolution rounds shrank the class without
eliminating it; each evolved version retains exactly one executed
write, on a phrasing family its round never trained on. The measured
conclusion: prompt rules chase phrasings; the class fix belongs at the
tool layer (a confirmation contract on `update_salesforce_crm` /
`approve_discount`).

## Contents

- `runner.py` + `run.sh` — the harness: ADK Runner around the sample's
  `root_agent`, BigQuery Agent Analytics plugin logging every hop;
  `--instruction-file` swaps in an evolved skill without touching the
  sample.
- `cs_eval_spec.json` — scope, ground-truth rule, tool descriptions,
  and 18 golden pairs, all derived from the sample's own mock data.
- `questions_*.json` — evolve set (30 + 6 round-2 probes) and held-out
  exam (20 + 8 correction extension; figures and phrasings disjoint
  from the evolve set).
- `v0/v1/v2_instruction.md` — the skill lineage; `v1_candidates/` the
  round-1 competitors.
- `*_report.json` / `*_results.json` — every judged report and raw
  transcript behind the tables; `baseline_report.md` the first scored
  report in readable form.

## Reproduce

1. Sparse-clone the sample (never vendored here):
   `git clone --depth 1 --filter=blob:none --sparse https://github.com/google/adk-samples.git && cd adk-samples && git sparse-checkout set python/agents/customer-service`
2. `uv init --bare` a harness dir next to it; `uv add --editable
   <clone>/python/agents/customer-service "google-adk[bigquery-analytics]"
   google-cloud-bigquery-storage`; copy `.env.example` to `.env` and
   fill in your project.
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

1. Overwrite family across versions: offers at first contact, executed
   writes under imperative phrasings, one residual per round.
2. Round 2's poison rule: a failure's de-escalation consolidated as
   procedure ("adjust the price to match the user's expected total"),
   caught in diff review, confirmed by the held-out exam.
3. Guardrail refusal of an entire round under an undersized
   `--max-chars`: correct refusal, operator-parameter bug.
4. Judge noise at small n: behaviorally identical hc14 answers judged
   differently across versions — one session is 3.6pp at n=28.
5. A stall class (hc4/hc11/hc12: ask for identifiers instead of
   verifying) untouched by both rounds and invisible in aggregates.
