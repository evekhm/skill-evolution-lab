# Evolve supervisor skill to v1 (44.0% -> 81.8%)

URL: https://github.com/evekhm/skill-evolution-lab/pull/48

## Skill Evolution: supervisor v1

### Quality Before Evolution

| Metric | Value |
|--------|-------|
| Meaningful rate | 44.0% |
| Unhelpful rate | 56.0% |

### Candidate Eval Scores

| Metric | Baseline (v0) | Evolved (v1) |
|--------|:------------:|:-------------------:|
| Meaningful rate | 44.0% | 81.8% |
| Unhelpful rate | 56.0% | 18.2% |
| Skill size | | 5789 chars |

### Trace Selector (reproducibility)

Evolved from BigQuery traces where: app=`knowledge_supervisor`, agent_version=`any`, labels: sample=standard-deployed, window: 6h

Run: `2026-07-22_095614_evolution`

