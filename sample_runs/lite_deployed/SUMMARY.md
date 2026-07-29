# Deployed Lite Run Summary — PR #57 (2026-07-29, aligned)

This run uses the SAME 13-question set as the local lite profile at
every stage (the question-set alignment fix in PR #56).

- Cloud Run job execution span: **39m 05s** (18:32:39 -> 19:11:44 UTC)
- Result: V0 15.4% -> winner 100.0% on the run's 13-session slice
- Publish gate: 10 passed, 0 failed (full CI-equivalent suite,
  in-container) -> registry push -> PR #57 opened by the job
- PR checks: Golden Eval, Load Test — green
- Outcome: PR closed as the demo sample; registry rolled back to V0

## Where the time goes (from the job log timestamps)

| Stage | Duration |
|---|---|
| Container provisioning + start | ~45s |
| Pre-flight traffic (13 sessions against deployed V0, via Agent Engine) | 10m 17s |
| Pre-flight scoring (LLM judge) | 55s |
| Evolution: analyst fleet + candidate generation + candidate scoring | ~13m |
| Winner re-validation + snapshots + version compare | ~12m |
| Publish gate (full golden suite) | 1m 20s |
| Registry push + PR creation | ~30s |

Comparison with the pre-alignment run (PR #51): 91m 27s total on
55-session batches. Alignment brings deployed lite to roughly local
lite's wall time (~37 min); the residual gap is Agent Engine serve
latency on every conversation turn (~48s vs ~23s per conversation —
small batches use the concurrency budget less efficiently).

Note on baselines: the deployed pre-flight judge scores whole 4-turn
sessions without golden-answer matching (a known SDK limitation on
the BigQuery path), so its V0 percentage is stricter than the local
golden-matched scorer's and the two baselines are not directly
comparable. The winner percentages are comparable (both saturate).
