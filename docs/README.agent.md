# Skill Evolution Lab - Agent Reference

This document is optimized for consumption by autonomous AI agents, orchestrators, and LLM-based coding assistants. It omits narrative instructions in favor of concrete commands, structures, and schemas.

## System Overview
A multi-agent GCP system (ADK + Vertex AI Agent Engine) that learns from its own execution traces.
The system consists of:
1. **knowledge_supervisor**: Root agent (Vertex AI Agent Engine).
2. **policy_agent**: Specialist (Cloud Run A2A). Evolves its `SKILL.md`.
3. **hr_calculator**: Deterministic specialist (Cloud Run A2A).
4. **quality_agent**: Runs daily via Cloud Scheduler, evaluates BQ logs, files GitHub Issues for failures.
5. **skill_evolution_agent**: Runs on demand or via heuristic, consumes GitHub Issues, patches `SKILL.md`, and creates a PR.

## Directory Structure
- `agents/enterprise/`: Agents serving end users (supervisor, policy, hr). Configuration and `SKILL.md` files are located here. Target for evolution patches.
- `agents/workflow/`: Operational agents (quality, evolution, traffic_generator).
- `eval/`: Golden test datasets (`eval/data/golden_evals.json`), evaluators, and the `uv run pytest` test suite.
- `scripts/`: Deployment and setup scripts.

## Environment Variables (`.env`)
Required environment configuration:
- `PROJECT_ID`: GCP Project ID.
- `REGION`: GCP Region (default: `us-central1`).
- `DATASET_ID`: BigQuery dataset for agent logs.
- `GITHUB_TOKEN`: Requires `repo` and `pull_request` scopes for issue/PR creation.

## Core Execution Commands
Execute these commands from the repository root:

**1. Local Python Setup:**
(Note to Agent: On Google internal hostnames, you must bypass the local config cache)
```bash
UV_INDEX_URL="https://pypi.org/simple" UV_EXTRA_INDEX_URL="" PIP_CONFIG_FILE=/dev/null bash scripts/local/local_setup.sh
```

**2. Run Local Tests:**
Requires valid `gcloud auth application-default login` pointing to a project with Vertex AI API enabled.
```bash
uv run pytest eval/tests/ -v
```

**3. Local Evolution Run (Simulation):**
Requires `.env` and `GITHUB_TOKEN`.
```bash
bash scripts/local/local_demo.sh
```

**4. GCP Infrastructure Provisioning:**
```bash
source .env
gcloud config set project $PROJECT_ID
bash scripts/setup/setup_gcp.sh
```

**5. Deploy Stack to GCP:**
```bash
bash scripts/deploy/deploy_gcp.sh
```

## Evolution Loop Subsystem
1. Logs are written to BigQuery `agent_analytics` dataset continuously.
2. `quality_agent` queries BigQuery, scoring traces against `eval/data/golden_evals.json`. If grade < threshold, files a GitHub Issue containing the trace payload.
3. `skill_evolution_agent` scrapes open GitHub Issues. It spawns independent sub-agents to trace the failure, mutates the candidate's `SKILL.md` and generates a GitHub Pull Request.
4. CI Actions (`.github/workflows/eval.yml`) automatically test the new `SKILL.md` budget.
