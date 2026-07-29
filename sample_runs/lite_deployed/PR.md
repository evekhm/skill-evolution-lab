# Evolve supervisor skill to v1 (21.8% -> 100.0%)

State: CLOSED (closed as the demo sample after all checks passed)


## Skill Evolution: supervisor v1

### Quality Before Evolution

| Metric | Value |
|--------|-------|
| Meaningful rate | 21.8% |
| Unhelpful rate | 74.5% |

### Candidate Eval Scores

| Metric | Baseline (v0) | Evolved (v1) |
|--------|:------------:|:-------------------:|
| Meaningful rate | 21.8% | 100.0% |
| Unhelpful rate | 74.5% | 0.0% |
| Skill size | | 3916 chars |

### Trace Selector (reproducibility)

Evolved from BigQuery traces where: app=`knowledge_supervisor`, agent_version=`any`, labels: (none), window: 6h

Run: `2026-07-29_003722_evolution`


---
PR #51 — opened by the job 2026-07-29 02:08 UTC, all checks green
(Golden Eval, Load Test, GitGuardian), closed as the demo's
reviewable sample; registry rolled back to V0 afterwards.
