# Scripts

Automation scripts for the Knowledge Supervisor project, organized by purpose.

All scripts are run from the **project root** and load `.env` automatically.

## Directory Structure

```
scripts/
  setup/          One-time environment provisioning and teardown
  local/          Local development workflow
  deploy/         Deployment (deploy.sh only)
  demo/
    reactive_loop/  V1 reactive loop demos + Vertex AI prompt management
    skill_evolution/ V2 skill evolution pipeline scripts
  experiment/     Autonomous experiment orchestrators
  test/           Quality evaluation and verification
  utils/          Reporting and analysis utilities
```

## setup/ -- Environment Provisioning

| Script | Description |
|--------|-------------|
| `setup_gcp.sh` | One-time GCP project setup: enables APIs, creates BigQuery dataset, Artifact Registry repo, and IAM roles |
| `setup_github.sh` | Sets up GitHub integration: installs deps, creates issue labels, configures GitHub App and Workload Identity |
| `cleanup_github.sh` | Closes and deletes all PRs and issues in a GitHub repo (for resetting demo state) |

```bash
bash scripts/setup/setup_gcp.sh
bash scripts/setup/setup_github.sh
```

## local/ -- Local Development

| Script | Description |
|--------|-------------|
| `local_setup.sh` | Sets up the local Python environment: syncs deps with `uv`, verifies GCP auth, tests agent imports |
| `local_start.sh` | Starts all agents locally (policy_agent, hr_calculator, knowledge_supervisor) on localhost |
| `reset_local_loop.sh` | Restores the repo to baseline state for re-running the quality loop |
| `run_local_quality_loop.sh` | Runs the full quality improvement cycle locally (traffic, quality report, remediation, verify) |

```bash
bash scripts/local/local_setup.sh
bash scripts/local/local_start.sh          # start agents
bash scripts/local/local_start.sh stop     # stop agents
bash scripts/local/run_local_quality_loop.sh --scenario out_of_scope
```

## deploy/ -- Deployment

| Script | Description |
|--------|-------------|
| `deploy.sh` | Deploys all 5 agents to GCP in sequence (policy_agent, hr_calculator, supervisor, quality, traffic) |

```bash
bash scripts/deploy/deploy_gcp.sh
```

## demo/ -- Demos & Traffic

### demo/reactive_loop/ -- V1 Reactive Loop

| Script | Description |
|--------|-------------|
| `run_demo.sh` | Demo orchestrator: runs the agent improvement cycle with interactive pauses |
| `run_scenario1.sh` | Scenario 1: Happy Path -- automated quality fix for expenses/holidays/benefits |
| `run_scenario2.sh` | Scenario 2: New Topic -- human-in-the-loop for tuition reimbursement |
| `run_scenario3.sh` | Scenario 3: Regression Detection via Conversational Analytics |
| `prompt_manager.sh` | Manage prompts in Vertex AI Prompt Manager (setup/update/show) |
| `prompt_manager.py` | Python implementation of Vertex AI Prompt Manager operations |
| `show_prompt.sh` | Display current prompt text and version from Vertex AI |

### demo/skill_evolution/ -- V2 Skill Evolution

| Script | Description |
|--------|-------------|
| `run_demo.sh` | Full E2E pipeline: `--full` (205q, ~2h), `--quick` (22q, ~15min), `--reuse-v0` (skip V0 traffic). Handles traffic, two-step scoring, agentic evolution with best-of-N, and V0 restore. |
| `run_demo_autonomous.sh` | Thin wrapper around `run_demo.sh` that adds Claude Code sessions for skill review after each evolution step and ANALYSIS.md generation at the end. All mechanical work is done by `run_demo.sh`. |
| `score.sh` | Score conversations: SDK turn tagger + evolution scorer with ground truth. Auto-detects `eval/data/golden_evals.json` for per-question embedding matching. Disable with `--golden-evals none`. |
| `extract_ground_truth.sh` | Extract compact ground truth from golden Q&A pairs via LLM. Can update `agent_context.json` directly with `--update-config`. |
| `verify_turn_tagger.sh` | Verify turn tagger accuracy against simulator-tagged conversations |

### demo/ (shared)

| Script | Description |
|--------|-------------|
| `generate_questions.sh` | Generates synthetic questions for eval and demo use |
| `generate_traffic.sh` | Send traffic to agents: single query (no args / `-q`) or batch multi-turn (`--from-file`). Local by default, `--remote` for deployed. |

```bash
# Single query (replaces old send_local_query.sh)
bash scripts/demo/generate_traffic.sh                              # default question, local
bash scripts/demo/generate_traffic.sh -q "What is our PTO policy?" # custom question
bash scripts/demo/generate_traffic.sh -q "PTO policy?" --remote    # deployed agents

# Batch multi-turn (for eval / evolution)
bash scripts/demo/generate_traffic.sh --from-file eval/data/questions/demo_quick.json
bash scripts/demo/generate_traffic.sh --from-file eval/data/questions/full_205.json --concurrency 5

# Deployed smoke test (REST API, no Python)
bash scripts/test/smoke_test_deployed.sh -q "What is the PTO policy?"

# Scoring & evolution
bash scripts/demo/skill_evolution/score.sh -i eval/runs/.../traffic.json
bash scripts/demo/skill_evolution/score.sh -i eval/runs/.../traffic.json --golden-evals none  # disable

# Ground truth extraction from golden evals
bash scripts/demo/skill_evolution/extract_ground_truth.sh --input eval/data/golden_evals.json
bash scripts/demo/skill_evolution/extract_ground_truth.sh --input eval/data/golden_evals.json \
    --update-config eval/data/agent_context.json
```

## experiment/ -- Autonomous Experiments

| Script | Description |
|--------|-------------|
| `create_evolution_pr.sh` | Create PR with evolved skill and quality metrics for review |
| `run_agentic_experiment.sh` | Standard vs agentic evolution A/B test (best-of-N) |
| `run_variance.sh` | Variance & best-of-N experiment orchestrator |
| `watchdog.sh` | Fault-tolerance monitor: auto-restarts orchestrator on crash |

```bash
# Full E2E pipeline (anyone can run, no Claude needed)
./scripts/demo/skill_evolution/run_demo.sh --full              # V0→V1→V2, ~2h
./scripts/demo/skill_evolution/run_demo.sh --full --reuse-v0   # Skip V0 traffic, ~1.5h
./scripts/demo/skill_evolution/run_demo.sh --quick             # Quick 22-question test

# Autonomous with Claude Code (adds skill review + ANALYSIS.md)
nohup bash scripts/demo/skill_evolution/run_demo_autonomous.sh --reuse-v0 > /tmp/evolution.log 2>&1 &
tail -f eval/runs/*_evolution_e2e/master.log

```

## test/ -- Quality Evaluation

| Script | Description |
|--------|-------------|
| `smoke_test_deployed.sh` | Smoke test deployed agents via REST API (discovers Reasoning Engine, sends queries) |
| `quality_report.sh` | Runs quality evaluation on recent agent sessions from BigQuery using LLM judge |
| `verify_questions.sh` | Shell wrapper for `eval/scoring/verify_questions.py` (parses issue markdown, runs queries, judges responses) |

```bash
# Smoke test after deploying
bash scripts/test/smoke_test_deployed.sh                              # default questions
bash scripts/test/smoke_test_deployed.sh -q "How many PTO days left?" # custom query

bash scripts/test/quality_report.sh --time-period 1h
bash scripts/test/verify_questions.sh path/to/issue_file.md
```

## utils/ -- Reporting & Analysis

| Script | Description |
|--------|-------------|
| `latency_report.sh` | Trace latency analyzer: shows timing tree for agent sessions from BigQuery |
| `latency_report.py` | Python implementation: fetches traces, renders execution tree with waterfall |
| `print_load_report.sh` | Pretty-prints a load test report with per-topic breakdown |
| `print_load_report.py` | Python implementation of load test report rendering |

```bash
bash scripts/utils/latency_report.sh --time-period 1h --verbose
bash scripts/utils/print_load_report.sh eval/load_test_report.json
```
