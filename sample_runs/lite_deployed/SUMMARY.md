# Deployed Lite Run Summary — PR #58 (2026-07-29, fully aligned)

Every component matches the local lite profile: the same 13-question
set (`two_defect_lite.json`) for evolution and candidate scoring, the
same evolution parameters (1 round, 2 candidates), and
`gemini-3.5-flash` for the supervisor, both specialists, the analyst
fleet, and the LLM judge.

- Cloud Run job execution span: **32m 52s** (22:59:19 -> 23:32:11 UTC)
- Pre-flight baseline: V0 7.4% on 27 REAL BigQuery sessions (a 6-hour
  window of live traffic — the production detection path; earlier
  sample runs fell back to generated traffic when the window was empty)
- Candidate scoring (13-question set, same judge as local):
  candidate_1 38.5%, candidate_2 76.9% -> winner 76.9%
- Publish gate: 10 passed, 0 failed -> registry push -> PR #58 opened
  by the job

## Where the time goes (from the job log timestamps)

| Stage | Duration |
|---|---|
| Container provisioning + start | ~1m 13s |
| Pre-flight (judge 27 BigQuery sessions — no traffic generation) | ~2m 45s |
| Evolution: analyst fleet + candidates + scoring on 13 questions | ~26m |
| Publish gate (full golden suite) | 1m 50s |
| Registry push + PR creation | ~25s |

## Why these numbers are credible

The judge scores real spreads now (38.5% vs 76.9% between candidates,
rates summing to 100%) instead of the saturated or zeroed values seen
while the scoring endpoint and judge model were misaligned. The
winner's 76.9% is a same-instrument number: the identical scorer,
model, and question set that local runs use.
