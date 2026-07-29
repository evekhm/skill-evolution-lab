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
- GitHub credential for issue/PR creation (`repo` scope): `GITHUB_TOKEN` or
  `GH_TOKEN` env var, or the `github-pat` Secret Manager secret — the code
  accepts any of the three. Not part of `.env.example`.

## Core Execution Commands
Execute these commands from the repository root:

**1. Local Python Setup:**
> [!WARNING]
> **Sandboxed Agent Constraint:** The dependency `a2a-sdk` required by this project is hosted in a private Artifact Registry. If you are an autonomous sandboxed agent running `uv sync` or `local_setup.sh` inside an isolated container, **it will fail** with a 401 Unauthorized error because you do not have the necessary local authentication credentials. The user MUST run the dependency bootstrapping steps natively on their host (where they are authenticated) or grant explicit `unsandboxed` permissions for the process.

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
bash scripts/demo/skill_evolution/run_lite.sh --local
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
1. Logs are written continuously to the BigQuery `agent_logs` dataset (`agent_events` table).
2. `quality_agent` queries BigQuery, scoring traces against `eval/data/golden_evals.json`. If grade < threshold, files a GitHub Issue containing the trace payload.
3. `skill_evolution_agent` scrapes open GitHub Issues. It spawns independent sub-agents to trace the failure, mutates the candidate's `SKILL.md` and generates a GitHub Pull Request.
4. CI Actions (`.github/workflows/eval.yml`) automatically test the new `SKILL.md` budget.

## Code Conventions

- Python scripts in `scripts/` must have `.sh` wrappers that source `.env`.
- Always use LLM-as-judge for quality scoring, never string matching.
- No `Co-Authored-By` lines in git commits.
- All V2/skill-evolution changes must keep the V1 demo fully functional.
- Run autoformat and tests before pushing.
- Never push code without proving it works end-to-end locally first.
- No inline `python3 -c` blocks in `.sh` files.

## Output Discipline (long runs)

Experiments, traffic generation, and demo runs produce verbose output:

1. Redirect output to files, then tail the summary:
   ```bash
   command_here > eval/some_log.log 2>&1
   tail -20 eval/some_log.log
   ```
2. Never echo raw HTTP/API logs into a conversation or PR — use `2>&1 | tail -N`.
3. Report key results as numbers, not raw data dumps.

## Evolution Test Cycle (invoke with: "run evolution test cycle")

When the user asks to run an evolution test cycle, follow this EXACT procedure.
Print timing for every step. Review every skill before proceeding.

**Setup:**
```
source .env
RUN_DIR="eval/runs/$(date +%Y-%m-%d_%H%M%S)_evolution"
mkdir -p "$RUN_DIR"
```

**Reusable V0 data (Do not regenerate V0 traffic unless asked explicitly):**
- V0 reference run: `eval/skill_evolution/reference_runs/v0_baseline_demo/`
- V0 traffic: `eval/skill_evolution/reference_runs/v0_baseline_demo/v0_traffic.json` (205q)
- V0 quality report: `eval/skill_evolution/reference_runs/v0_baseline_demo/v0_quality_report.json`
- Quick questions: `eval/data/questions/demo_quick.json` (22q)
- V0 skill baseline: `agents/enterprise/policy_agent/skill/SKILL.v0.md`

**Golden reference (target):** V0=60% → V1=94% → V2=98% (May 16 run)

**Scorer:** Use `score_conversations.py` (SDK scorer) for all scoring. It handles
ground truth, turn tagging, trajectory sampling, and quality scoring in a single pass.

### Steps:

1. **Score V0** (skip if scorer unchanged — reuse existing report)
   - `score_conversations.py -i results.json -o quality_report.json --tag-turns --trajectory-samples 100 --report`
   - Print: meaningful_rate, unhelpful_rate, total_sessions
   - Print: elapsed time

2. **Evolve V0→V1** (ALWAYS `--agentic`, use `--candidates 3` for best-of-N)
   - `evolve.py --agentic --model gemini-2.5-pro --max-workers 10 --candidates 3 --candidates-dir $RUN_DIR/v1_candidates`
   - Print: elapsed time, patch count, analyst count

3. **Review V1 skill** (MANDATORY before traffic)
   - Print: file size (expect 8-15KB), version, section headings
   - Check: keyword mappings table exists, anti-patterns section exists
   - Check: no excessive repetition, no bloat
   - Write summary: what's good, what's missing vs golden V1
   - If skill looks bad: STOP and tell user. Do NOT proceed.

4. **Deploy V1 + quick traffic** (22 questions, ~3 min). If asked to do a full, run all 205 questions.
   - Backup V0 skill first, deploy V1, run traffic generator
   - Print: elapsed time

5. **Score V1**
   - Print: meaningful_rate, delta from V0, elapsed time

6. **Evolve V1→V2** (ALWAYS `--agentic`)
   - Print: elapsed time, patch count

7. **Review V2 skill** (same checks as step 3)
   - Write summary comparing V2 vs V1

8. **Deploy V2 + quick traffic + score**
   - Print: meaningful_rate, delta from V1, elapsed time

9. **Restore V0 skill** (always restore after testing)

10. **Print final summary table:**
    ```
    | Version | Meaningful | Unhelpful | Delta | Time |
    ```

### Rules:
- NEVER skip skill review (steps 3 and 7)
- NEVER run without --agentic
- NEVER use full 205q set for iteration (use 22q quick)
- ALWAYS restore V0 skill at the end
- ALWAYS print elapsed time per step
- Full handbook: `docs/skill-evolution/QUICK_EVOLUTION_RUNBOOK.md`

## Key Paths

- Agent code: `agents/enterprise/` (policy_agent, knowledge_supervisor, hr_calculator)
- Workflow agents: `agents/workflow/` (skill_evolution_agent, quality_agent, traffic_generator)
- Eval data & results: `eval/`
- Blog & docs: `docs/skill-evolution/`
- Skills (V0 baseline): `agents/enterprise/*/skill/SKILL.md`
- V0 baselines: `agents/enterprise/*/skill/SKILL.v0.md` (next to SKILL.md)
