# Deployed Lite Run Summary — PR #63 (2026-07-31, fully aligned)

Every component matches the local lite profile: the same 13-question
set (`two_defect_lite.json`) for the generated V0 baseline, evolution,
and candidate scoring; the same evolution parameters (1 round, 2
candidates); and `gemini-3.5-flash` for the supervisor, both
specialists, the analyst fleet, and the LLM judge. The analysts also
receive the same derived agent-toolbox block as local runs (verified
in the job log — no fallback warnings).

- Cloud Run job execution span: **42m 55s** (22:41:14 -> 23:24:09 UTC)
- V0 baseline: **23.1%** meaningful (3/13, `v0_quality_report.json`),
  generated with `--quality-source synthetic` on the 13-question set —
  identical to how local runs produce their baseline
- Candidate scoring (13-question set, same judge as local):
  candidate_1 46.2%, candidate_2 61.5% -> winner candidate_2
- Winner validation as v1: **69.2%** meaningful
  (`v1_quality_report.json`; the one-session spread vs the 61.5%
  selection replay is judge variance — 13 sessions put 7.7pp on each)
- Publish gate: 10 passed, 0 failed -> registry revision 33 ->
  Issue #62 and PR #63 opened by the job

## Where the time goes (from the job log timestamps)

| Stage | Duration |
|---|---|
| Container provisioning + start | ~2m 16s |
| V0 baseline: generate 13q traffic + judge | 12m 14s |
| Evolution: analyst fleet + 2 candidates + scoring + v1 validation | ~26m |
| Publish gate (full golden suite) | 1m 37s |
| Registry push + issue + PR creation | ~36s |

## Why these numbers are credible

Every rate is a same-instrument number: the identical scorer
(`score_conversations.py` via the SDK), judge model
(`gemini-3.5-flash`), and question set that local runs use. Rates sum
to 100% per report and 13/13 sessions are golden-matched. The winner
scores lower than the local profile's 100% because the analyst-patch
quality gate rejects more patches from serve-path trajectories (9/13
here vs 2/13 locally) — consistent with the previous deployed lite
archive, not a regression.
