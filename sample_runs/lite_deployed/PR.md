# Evolve supervisor skill to v1 (61.5% -> 85.5%)

URL: https://github.com/evekhm/skill-evolution-lab/pull/47

## Skill Evolution: supervisor v1

### Quality Before Evolution

| Metric | Value |
|--------|-------|
| Meaningful rate | 61.5% |
| Unhelpful rate | 38.5% |

### Candidate Eval Scores

| Metric | Baseline (v0) | Evolved (v1) |
|--------|:------------:|:-------------------:|
| Meaningful rate | 61.5% | 85.5% |
| Unhelpful rate | 38.5% | 12.7% |
| Skill size | | 6180 chars |

### Trace Selector (reproducibility)

Evolved from BigQuery traces where: app=`knowledge_supervisor`, agent_version=`any`, labels: sample=lite-deployed, window: 6h

Run: `2026-07-22_083631_evolution`

