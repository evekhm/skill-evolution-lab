# Evolve supervisor skill to v1 (15.4% -> 100.0%)

State: CLOSED (closed as the demo sample after all checks passed)

## Skill Evolution: supervisor v1

### Quality Before Evolution

| Metric | Value |
|--------|-------|
| Meaningful rate | 15.4% |
| Unhelpful rate | 76.9% |

### Candidate Eval Scores

| Metric | Baseline (v0) | Evolved (v1) |
|--------|:------------:|:-------------------:|
| Meaningful rate | 15.4% | 100.0% |
| Unhelpful rate | 76.9% | 0.0% |
| Skill size | | 2949 chars |

### Trace Selector (reproducibility)

Evolved from BigQuery traces where: app=`knowledge_supervisor`, agent_version=`any`, labels: (none), window: 6h

Run: `2026-07-29_183325_evolution`

