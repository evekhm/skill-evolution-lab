# Sample Runs

Real, unedited outputs from every demo configuration (paths, project
numbers, and service hashes replaced with placeholders). Each folder
holds the run's `SUMMARY.md`, the PR artifact, the judged V0 report,
the skill versions, and the full console log.

| Sample | Config | Wall time | Result (ground truth, unseen questions) |
|---|---|---|---|
| [lite_local](lite_local/) | 13q, 1 round, 2 candidates, local sandbox | 26-44 min | 61.5% -> 92.3% (+30.8pp) |
| [standard_local](standard_local/) | 25q, 1 round, 3 candidates, local sandbox | 45m 10s | 48.0% -> 76.0% (+28.0pp) |
| [standard_local_2rounds](standard_local_2rounds/) | 25q, 2 rounds — the writeup configuration | 92m 17s | **36.0% -> 84.0% (+48.0pp)** |
| [full_local](full_local/) | 55q split, agent-decided, local sandbox | 202m 19s | 34.8% -> 78.3% (+43.5pp) |
| [lite_deployed](lite_deployed/) | 13-session labeled slice, Cloud Run job | ~53 min | PR #47: 61.5% -> 85.5%, CI gate green |
| [standard_deployed](standard_deployed/) | 25-session slice, 3 candidates | ~78 min | PR #48: 44.0% -> 81.8%, CI gate green |
| full_deployed | 55-session slice, agent-decided | running | pending |
| [deployed_incumbent_refusal](deployed_incumbent_refusal/) | unscoped window (safety behavior) | ~54 min | evolved 58.2% < baseline 72.0%: NO PR opened, no email — the loop refuses regressions |

Selection scores inside each run are measured on the evolve set; the
result column above is always the held-out measurement (or the PR's
grounded rates for deployed runs). Local runs publish nothing; the
deployed PRs stay unmerged as reviewable artifacts.
