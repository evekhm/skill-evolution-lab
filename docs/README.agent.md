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

All dependencies, including `a2a-sdk`, are public on PyPI.

```bash
bash scripts/local/local_setup.sh
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

## Verification Contract (MANDATORY before reporting anything)

Every rule below exists because its violation produced a wrong result
in this repo. Do not report a number, claim, or "done" that has not
passed the applicable checks.

### Before reporting any metric

1. Trace it to an artifact (report JSON, run log, PR title). If you
   cannot name the file, you do not have the number.
2. Open the underlying conversations when a number is 0%, 100%, or
   surprising. Check for error-shaped answers:
   `grep -c "ERROR:" <traffic.json>` — a judge scores error strings
   as unhelpful without complaint (this produced a fake 0% twice).
3. Sanity-check the judge output: meaningful + unhelpful + partial
   must account for all sessions. `0.0 meaningful AND 0.0 unhelpful`
   means scoring FAILED, not that candidates are bad.
4. Name the instrument. A percentage is meaningless without: which
   scorer, which judge model, which question set. Numbers from
   different instruments never share a comparison row uncaveated.
5. Confirm the question set from the run's own binding log
   (`Binding overrides` line), never from the profile's intent.

### Before claiming two configurations are aligned

Verify EVERY component from live state, not from memory or docs:
question file (binding log), evolution parameters (job args), each
agent's model (`gcloud run services describe <svc>` env, Agent Engine
config), judge model and scorer module, conversation depth. In this
repo a claimed-identical setup was wrong three times in one day
(specialist models, judge model, baseline traffic source).

### Demo-specific facts that override intuition

- There is NO real traffic in this project. BigQuery contains residue
  from earlier test runs only. Deployed demo baselines are GENERATED
  (`--quality-source synthetic`) on the profile's question set,
  identically to local runs.
- V0's held-out exam score is REUSED from the committed reference
  (`eval/data/reference/`, checksum-guarded, auto-rebaselines when
  the system changes). Never re-measure it per run.
- gemini-3.x models are served from the GLOBAL endpoint only. Never
  assign an infra region to `GOOGLE_CLOUD_LOCATION`; use the
  MODEL_LOCATION-or-global pattern already present in every module.

### When fixing a bug

Fix the CLASS, not the instance: grep the whole repo for the pattern
before declaring it fixed, and list every occurrence in the commit
message. (The same env-stomp bug was fixed six times in five files
because the first five fixes stopped at the instance; the same
guessed-routing-assert bug existed in two separate extraction paths.)

### Runs and processes

- Never edit a script while a run executes (bash reads lazily —
  edits corrupt the running process).
- Killing a demo run means killing `run_demo.sh` AND its python
  children (`skill_evolution_agent/main.py`,
  `traffic_generator/main.py`), then verifying with `ps`. Orphans
  keep evolving and DEPLOYING skills after the parent dies.
- After any kill: verify all three `SKILL.md` files are `version: "0"`.
- Two agents/sessions must never share one checkout or branch.

### Authority (the repository owner decides, not the agent)

- Never close, merge, or reopen ANY pull request without the owner's
  explicit instruction — including PRs you created, including the
  demo flow's "close the evolution PR as a sample" step.
- Never push to main directly; work goes through a branch and PR.
- Pushing, publishing, or activating anything requires the owner's
  explicit word each time; prior approvals do not carry over.

## Reporting and Documentation Conventions

- Results tables ALWAYS show two measurements per run: the evolve set
  (V0 -> winner on its training questions) and the held-out exam
  (V0 -> winner on the shared 55-question set). One without the other
  is half the story. Deployed runs have no held-out exam — mark the
  column "—".
- Findings and status reports are tables; timestamps in Pacific time.
- Docs and tables carry MEASURED values only, with the source
  artifact nameable. Write "being re-measured" rather than an
  estimate or a stale number.
- Writing style: plain declarative sentences. No aphorisms, no
  "X is the Y" reveals, no bolded dramatic openers, no rhetorical
  pivots. Never transplant the owner's chat phrasing into docs. No
  unexplained jargon or internal codenames — define on first use.
- When an instruction is ambiguous — especially if the action deletes
  or rewrites something — state your interpretation in one sentence
  and confirm, or take the minimal reading that satisfies the literal
  words. Never resolve ambiguity toward your own preference.

## Archiving Sample Runs

Every archived run in `sample_runs/` must be sanitized before commit:

```bash
sed -i -E 's|/home/[a-zA-Z_]+|~|g; s|<PROJECT_NUMBER>|<project-id>|g;
           s|<service-hash>-uc\.a\.run\.app|<service-hash>|g;
           s|reasoningEngines/[0-9]+|reasoningEngines/<engine-id>|g' <files>
```

Replace the real project number with the project id, scrub home paths
INCLUDING truncated forms (`/home/user_na...` inside cut-off dict
reprs), service URL hashes, and reasoning-engine ids. Then verify:
`grep -rl '<project number>\|<home dir>\|<service hash>' <folder>`
must return nothing. Index rows in `sample_runs/README.md` must equal
the archive's own SUMMARY numbers exactly.

## Session State

`STATUS.md` at the repo root is a private session handover document.
It is kept in a LOCAL-ONLY commit at the top of the local branch and
is never pushed to the public repository. Uncommit it before public
pushes; re-commit after.
