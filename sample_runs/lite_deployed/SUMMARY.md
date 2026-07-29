# Deployed Lite Run Summary — PR #51 (2026-07-29)

- Cloud Run job execution span: **91m 27s** (00:37:02 -> 02:08:29 UTC)
- Result: V0 21.8% -> winner 100.0% on the run's BigQuery slice
  (55 sessions, 12 meaningful at baseline)
- Publish gate: 10 passed, 0 failed (full CI-equivalent suite,
  in-container) -> registry push -> PR #51 opened by the job
- PR checks: Golden Eval, Load Test, GitGuardian — all green
- Outcome: PR closed as the demo sample; registry rolled back to V0
  (newest revision content-verified: `version: "0"`, 673 chars)

## Where the time goes (from the job log timestamps)

| Stage | Duration |
|---|---|
| Container provisioning + start | ~35s |
| Pre-flight traffic (55 sessions against deployed V0, via Agent Engine) | 15m 51s |
| Pre-flight scoring (LLM judge) | 3m 24s |
| Evolution: analyst fleet + candidate generation + candidate scoring | 36m 38s |
| Winner re-validation + snapshots + version compare | ~30m |
| Publish gate (full golden suite) | 3m 5s |
| Registry push + PR creation | ~25s |

The two conversation-heavy stages dominate: every turn goes through
the deployed Agent Engine + A2A path, which is what separates the
~91-minute deployed run from the ~37-minute local sandbox run.
