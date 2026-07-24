# Demo Run Summary — 2026-07-22_225941_demo_quick

- Wall time: 85m 43s
- BigQuery slice: `demo_run=2026-07-22_225941_demo_quick`
  (`EVOLUTION_TRACE_LABELS=demo_run=2026-07-22_225941_demo_quick bash scripts/test/show_traces.sh`)
- Published anywhere: NO (sandbox — registry/PR/issue disabled)
- Agents: LOCAL in-process; zero requests to the deployed stack
- Live skills: restored to V0; evolved versions snapshotted here as vN_*_skill.md

## Quality (meaningful rate)

| Version | Ground-truth rate | Judge rate | Matched |
|---|---|---|---|
| V0 baseline | 40.0% | 40.0% | 25/25 |
| v1 | 64.0% | 64.0% | 25/25 |
| v1 | 67.3% | 67.3% | 55/55 |
| v2 | 84.0% | 84.0% | 25/25 |
| v1 | 64.0% | 64.0% | 25/25 |
| v2 | 84.0% | 84.0% | 25/25 |
| candidate_1 | 80.0% | 80.0% | 25/25 |
| candidate_2 | 80.0% | 80.0% | 25/25 |
| candidate_3 | 80.0% | 80.0% | 25/25 |

## HELD-OUT RESULT — measured on unseen questions

| | V0 | Winner | Gain |
|---|---|---|---|
| Ground-truth rate | 41.8% | 67.3% | +25.5pp |

Winner previewed as PR: **v2 (84.0%)** -> pr_preview.md
Quality gate: winner 84.0% below the 95% threshold — another cycle is warranted

## Files worth reading

- `run.log` — full console output of the run
- `v0_quality_report.json/.md` — the judged baseline (failures = evolution input)
- `_score_candidate_N_report.json` — each candidate's replay score
- `vN_*_skill.md` — every evolved skill, per version
- `pr_preview.md` — the PR as a local artifact (branch name inside)
- `TRIAGE.md` — what evolution fixed vs what it cannot fix (if generated)
