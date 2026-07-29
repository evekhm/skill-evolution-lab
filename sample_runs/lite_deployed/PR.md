# Evolve supervisor skill to v1 (7.4% -> 76.9%)

State: OPEN (adjudication pending — the demo flow closes evolution PRs as samples on the owner's word)

## Skill Evolution: supervisor v1

### Quality Before Evolution

| Metric | Value |
|--------|-------|
| Meaningful rate | 7.4% |
| Unhelpful rate | 92.6% |

### Candidate Eval Scores

| Metric | Baseline (v0) | Evolved (v1) |
|--------|:------------:|:-------------------:|
| Meaningful rate | 7.4% | 76.9% |
| Unhelpful rate | 92.6% | 23.1% |
| Skill size | | 2821 chars |

### Trace Selector (reproducibility)

Evolved from BigQuery traces where: app=`knowledge_supervisor`, agent_version=`any`, labels: (none), window: 6h

Run: `2026-07-29_230035_evolution`

