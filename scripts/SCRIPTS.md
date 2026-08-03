# Scripts

Automation scripts for the Skill Evolution Lab, organized by purpose.

All scripts are run from the **project root** and load `.env` automatically.

## Directory Structure

```text
scripts/
  setup/           One-time environment provisioning and teardown
  local/           Local development workflow
  deploy/          Deployment to GCP
  demo/
    skill_evolution/  Skill evolution pipeline scripts
  test/            Quality evaluation and verification
  utils/           Reporting and analysis utilities
```

## setup/ -- Environment Provisioning

| Script | Description |
|--------|-------------|
| `setup_gcp.sh` | One-time GCP project setup: enables APIs, creates the BigQuery dataset, Artifact Registry repo, GCS bucket, IAM roles, and seeds the Skill Registry with V0 skills |
| `setup_github.sh` | GitHub integration (7 steps): issue labels, Workload Identity Federation, CI service account, repo variables, the `github-pat` secret, branch protection |
| `cleanup_github.sh` | Closes and PERMANENTLY deletes all PRs and issues in an explicitly named repo (`--repo owner/repo` + typed confirmation; `--yes` for automation) |
| `verify_setup.sh` | Read-only: runs all prerequisite checks (tools, auth, deployments, registry, CI wiring), one PASS/FAIL line each; exit code = failure count |

```bash
bash scripts/setup/setup_gcp.sh
GH_PAT=<token> bash scripts/setup/setup_github.sh
```

See the README's Step 0 for the full from-zero path.

## local/ -- Local Development

| Script | Description |
|--------|-------------|
| `local_setup.sh` | Sets up the local Python environment: syncs deps with `uv`, verifies GCP auth, tests agent imports |
| `local_start.sh` | Starts all agents locally (policy_agent, hr_calculator, knowledge_supervisor) on localhost |

```bash
bash scripts/local/local_setup.sh
bash scripts/local/local_start.sh          # start agents
bash scripts/local/local_start.sh stop     # stop agents
```

## deploy/ -- Deployment

| Script | Description |
|--------|-------------|
| `deploy_gcp.sh` | Deploys all 6 components to GCP in sequence (policy_agent, hr_calculator, supervisor, traffic, quality, evolution) |
| `submit_build.sh` | Shared async Cloud Build submit + poll (WIF-safe; used by the job deploys) |
| `cloudbuild_job.yaml` | Shared Cloud Build config for the job images (takes SDK_REPO/SDK_BRANCH build args) |

```bash
bash scripts/deploy/deploy_gcp.sh
```

## demo/ -- Demos & Traffic

### demo/skill_evolution/

| Script | Description |
|--------|-------------|
| `run_demo.sh` | Full local E2E pipeline: `--full` (205q, ~2h), `--quick` (22q, ~15min), `--reuse-v0` (skip V0 traffic). Handles traffic, scoring, agentic evolution with best-of-N, and V0 restore. |
| `run_lite.sh` | Lite demo profile (~17 min): 13q, 2 candidates, 1 round, supervisor target |
| `run_full.sh` | Full demo profile (~1-2 h): 55q + held-out split, agent-decided scope |
| `rollback_demo.sh` | One-command rollback: resets SKILL.md files to V0, republishes V0 to the Skill Registry, restarts the agents. Flags: `--baseline stub\|two-defect`, `--skip-redeploy` |
| `score.sh` | Score conversations: SDK turn tagger + quality scoring with ground truth. Auto-detects `eval/data/golden_evals.json` for per-question embedding matching. |
| `create_evolution_pr.sh` | Create a PR with the evolved skill and quality metrics for review |
| `extract_ground_truth.sh` | Extract compact ground truth from golden Q&A pairs via LLM. Updates `agent_context.json` with `--update-config`. |
| `v0_traffic_and_scoring.sh` | Generate and score a V0 baseline traffic run |
| `verify_turn_tagger.sh` | Verify turn tagger accuracy against simulator-tagged conversations |

### demo/ (shared)

| Script | Description |
|--------|-------------|
| `generate_questions.sh` | Generates synthetic questions for eval and demo use |
| `generate_traffic.sh` | Send traffic to agents: single query (no args / `-q`) or batch multi-turn (`--from-file`). Local by default, `--remote` for deployed. |

```bash
bash scripts/demo/generate_traffic.sh -q "What is our PTO policy?"
bash scripts/demo/generate_traffic.sh --from-file eval/data/questions/demo_quick.json
bash scripts/demo/skill_evolution/score.sh -i eval/runs/.../traffic.json
```

## test/ -- Quality Evaluation

| Script | Description |
|--------|-------------|
| `smoke_test_deployed.sh` | Smoke test deployed agents via REST API (discovers the Reasoning Engine, sends queries) |
| `quality_report.sh` | Runs quality evaluation on recent agent sessions from BigQuery using the LLM judge |
| `verify_questions.sh` | Shell wrapper for `eval/scoring/verify_questions.py` (parses issue markdown, runs queries, judges responses) |
| `show_traces.sh` | Inspect BigQuery traces: label distribution, or `--selector` to preview exactly what the evolution pre-flight fetches with the current env selector |

```bash
bash scripts/test/smoke_test_deployed.sh -q "How many PTO days left?"
bash scripts/test/quality_report.sh --time-period 1h
```

## utils/ -- Reporting & Analysis

| Script | Description |
|--------|-------------|
| `latency_report.sh` / `.py` | Trace latency analyzer: timing tree for agent sessions from BigQuery |
| `print_load_report.sh` / `.py` | Pretty-prints a load test report with per-topic breakdown |

```bash
bash scripts/utils/latency_report.sh --time-period 1h --verbose
bash scripts/utils/print_load_report.sh eval/load_test_report.json
```
