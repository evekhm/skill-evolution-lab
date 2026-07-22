# Demo Run Summary — 2026-07-22_024855_demo_full

- Wall time: 202m 19s
- BigQuery slice: `demo_run=2026-07-22_024855_demo_full`
  (`EVOLUTION_TRACE_LABELS=demo_run=2026-07-22_024855_demo_full bash scripts/test/show_traces.sh`)
- Published anywhere: NO (sandbox — registry/PR/issue disabled)
- Agents: LOCAL in-process; zero requests to the deployed stack
- Live skills: restored to V0; evolved versions snapshotted here as vN_*_skill.md

## Quality (meaningful rate)

| Version | Ground-truth rate | Judge rate | Matched |
|---|---|---|---|
| V0 baseline | 50.0% | 50.0% | 32/32 |
| v1 | 78.3% | 78.3% | 23/23 |
| candidate_1 | 84.4% | 84.4% | 32/32 |
| candidate_2 | 71.9% | 71.9% | 32/32 |
| candidate_3 | 75.0% | 75.0% | 32/32 |

Winner previewed as PR: **v1 (84.4%)** -> pr_preview.md
Quality gate: winner 84.4% below the 95% threshold — another cycle is warranted


## HELD-OUT RESULT — measured on unseen questions

| | V0 | Winner | Gain |
|---|---|---|---|
| Ground-truth rate | 34.8% | 78.3% | +43.5pp |

## Files worth reading

- `run.log` — full console output of the run
- `v0_quality_report.json/.md` — the judged baseline (failures = evolution input)
- `_score_candidate_N_report.json` — each candidate's replay score
- `vN_*_skill.md` — every evolved skill, per version
- `pr_preview.md` — the PR as a local artifact (branch name inside)
- `TRIAGE.md` — what evolution fixed vs what it cannot fix (if generated)
