# Sample Runs

Real, unedited outputs from every demo configuration (paths, project
numbers, and service hashes replaced with placeholders). Local run
folders hold the run's `SUMMARY.md`, the PR preview, the judged V0
report, the skill versions, and the full console log. Deployed run
folders hold the Cloud Run job log, plus the PR artifact when the
run opened one.

| Sample | Config | Wall time | Evolve set (V0 -> winner, training questions) | Held-out exam (V0 -> winner, unseen questions) |
|---|---|---|---|---|
| [lite_local](lite_local/) | 13q, 1 round, 2 candidates, local sandbox | ~54 min (~37 min of run + one-off live V0 exam) | 30.8% -> 100% (13q) | 40.0% -> 100% (55/55, +60.0pp) |
| [full_local](full_local/) | all 55q, agent-decided scope (evolved all 3 agents, stopped itself at 0 failures) | ~6h 51m | 40.0% -> 100% (55q) | 40.0% -> 100% (55/55, +60.0pp) |
| [lite_deployed](lite_deployed/) | Cloud Run job vs the live stack, 13-question set (same as local lite) | ~39 min | PR #57: 15.4% -> 100.0%; in-container publish gate 10/10, PR checks green; closed as sample, registry rolled back to V0 | — (deployed runs validate on their slice) |
| [full_deployed](full_deployed/) | 55-session slice, agent-decided | ~6h 14m | 16.4% -> 61.8% (+45.4pp); PR step failed (job container git bug); registry push rolled back to V0 | — |
| [deployed_incumbent_refusal](deployed_incumbent_refusal/) | unscoped window (safety behavior) | ~54 min | evolved 58.2% < baseline 72.0%: NO PR opened — the loop refuses regressions | — |

Selection scores inside each run are measured on the evolve set; the
result column above is always the held-out measurement (or the PR's
grounded rates for deployed runs). Deployed wall times are the Cloud
Run job execution span including container startup, so they run a few
minutes above the first-to-last log line. Local runs publish nothing;
the deployed PRs stay unmerged as reviewable artifacts.
