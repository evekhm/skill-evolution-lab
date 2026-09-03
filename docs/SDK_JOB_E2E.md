# SDK skill-evolution job — lab E2E runbook

How to reproduce this lab's recorded skill-evolution scenarios
(`sample_runs/`) using the **SDK's generic Cloud Run Job port**
(`deploy/skill_evolution_job/` in BigQuery-Agent-Analytics-SDK, branch
`feat/skill-evolution-job`) instead of the lab's own harness. The lab is
wired in exclusively through the job's host-hook seam:
`eval/skill_evolution_hooks.py` (`EVOLUTION_HOOKS=eval.skill_evolution_hooks`)
plus `eval/skill_evolution/sdk_job_requirements.txt` for the image.

The job's engine must be this repo's lab-stable one (it has the agentic
analyst kwargs: `error_analyst_fn`, `incumbent_score`,
`analyst_timeout_s`). Extract it once:

```bash
cd ~/projects/BigQuery-Agent-Analytics-SDK
mkdir -p /tmp/labstable_scripts
git show lab-stable:scripts/skill_evolution.py > /tmp/labstable_scripts/skill_evolution.py
git show lab-stable:scripts/quality_report.py > /tmp/labstable_scripts/quality_report.py
```

## Scenario 1 — lite_local (report-driven, no BigQuery, no publish)

From the lab repo root, with V0 restored
(`cp SKILL.v0.md SKILL.md` for all three agents,
`eval_cases.v0.json -> eval_cases.json`):

```bash
set -a; source .env; set +a
unset DATASET_ID TABLE_ID DATASET_LOCATION   # local traffic must not write BigQuery
export EVAL_QUESTIONS_FILE=eval/data/questions/two_defect_lite.json \
  EVOLUTION_PUBLISH=0 EVOLUTION_HOOKS=eval.skill_evolution_hooks \
  EVOLUTION_WORKDIR=$PWD AGENT_REGISTRY=eval/skill_evolution/agent_registry.json \
  SDK_SCRIPTS_DIR=/tmp/labstable_scripts PYTHONPATH=$PWD
RUN=/path/to/runs/$(date +%Y-%m-%d_%H%M%S)_lite_local_e2e; mkdir -p $RUN
```

1. **V0 baseline** — lab traffic + judge:

   ```bash
   uv run python agents/workflow/traffic_generator/main.py --multi-turn \
     --from-file eval/data/questions/two_defect_lite.json -o $RUN/v0_traffic.json \
     --concurrency 10 --max-turns 4 --local --local-agents
   uv run python eval/scoring/score_conversations.py -i $RUN/v0_traffic.json \
     -o $RUN/v0_quality_report.json --report --tag-turns --trajectory-samples all \
     --eval-spec eval/data/two_defect_eval_spec.json --concurrency 10
   ```

2. **Evolution via the SDK job** (report-driven mode):

   ```bash
   uv run python ~/projects/BigQuery-Agent-Analytics-SDK/deploy/skill_evolution_job/main.py \
     --report $RUN/v0_quality_report.json --mode supervisor \
     --run-dir $RUN --rounds 1 --candidates 2 --min-failures 5
   ```

   The job snapshots skills, checks the failure threshold, detects the
   bottleneck, and runs the lab-stable engine with the adapter's
   `error_analyst`, `toolbox`, and `score` hooks (each candidate is scored
   with real lab traffic + judge). The winner is installed to the live
   `SKILL.md` and snapshotted as `v1_*_skill.md`.

3. **Held-out exam** — repeat the traffic+score pair from step 1 with
   `--from-file eval/data/questions/two_defect_test.json` (55q), once with
   the winner installed and once after restoring
   `SKILL.v0.md -> SKILL.md` for the supervisor.

4. **PR preview** (parity with `sample_runs/lite_local/pr_preview.md`): with
   `EVOLUTION_PUBLISH=0` the job's `create_evolution_pr` writes
   `<run_dir>/pr_preview.md` and performs no git operations.

### Figures — recorded vs reproduced (2026-09-01, run `2026-09-01_003040_lite_local_e2e`)

| Leg | Recorded (`sample_runs/README.md`) | Reproduced via SDK job |
|---|---|---|
| Evolve set V0 (13q) | 38.5% (5/13) | 46.2% (6/13) |
| Evolve set winner (13q) | 100.0% | 100.0% |
| Exam V0 (55q) | 38.2% (21/55) | 41.8% (23/55) |
| Exam V1 (55q) | 98.2% | 100.0% (55/55) |
| Exam delta | +60.0pp | +58.2pp |
| pr_preview.md | yes | yes (dry_run, correct metrics table) |

Baselines are live-judged regenerated traffic, so they land within a
1–2-conversation band of the recorded ones; the end states match.

> Note: an earlier plan draft cited lite figures of 30.8→100 / 21.8→100 —
> those numbers are not baselines anywhere in `sample_runs/` (30.8 is the
> lite_deployed *unhelpful* rate). The recorded figures above are canonical.

## Scenario 2 — lite_deployed (full loop in Cloud Run, real PR)

Prerequisites:

- The hooks adapter must be **committed to this repo on GitHub**
  (`evekhm/skill-evolution-lab@main`): the job clones the repo at runtime
  and imports `EVOLUTION_HOOKS` from the clone.
- Image built with the lab-stable engine and the adapter's dependencies
  (from the SDK checkout, with
  `/tmp/labstable_scripts/skill_evolution.py` temporarily copied over
  `scripts/skill_evolution.py`):

  ```bash
  cd deploy/skill_evolution_job
  ./deploy.sh --project skill-evolution-lab --region us-central1 \
    --dataset agent_logs --dataset-location us-central1 \
    --github-repo evekhm/skill-evolution-lab --gh-secret github-pat \
    --gcs-bucket skill-evolution-lab-skill-evolution \
    --agent-registry eval/skill_evolution/agent_registry.json \
    --extra-requirements <lab>/eval/skill_evolution/sdk_job_requirements.txt \
    --smoke
  ```

  (`--github-repo` + `--gh-secret` together flip `EVOLUTION_PUBLISH=true`
  on the job — real PR mode.)

  This is automated by the lab's own deploy step:
  `agents/workflow/skill_evolution_agent/deploy.sh` (called by
  `scripts/deploy/deploy_gcp.sh` step 7) clones the SDK job source, runs
  the command above, and then persists the lab hook wiring on the job
  (`EVOLUTION_HOOKS`, `SDK_REPO`/`SDK_BRANCH`, quality scoping and model
  IDs) — so a scheduled fire needs no per-execution env.
- Deployed agents rolled back to V0:
  `bash scripts/demo/skill_evolution/rollback_demo.sh`.
- **`SDK_REPO` + `SDK_BRANCH` must be in the execution env** (the same
  values `.env` uses: the public fork + `lab-stable`). This repo's
  `ensure_sdk.py` (imported at module level by
  `eval/scoring/score_conversations.py` and, via the policy agent's
  skill loader, by the agentic analysts and the registry publish path)
  aborts when none of `SDK_DIR`/`SDK_REPO`/`SDK_BRANCH` are set — and
  the Cloud Run env sets none of them. Symptom when missing: every
  analyst warns `SDK_REPO and SDK_BRANCH environment variables must be
  set...` and every candidate score comes back "unmeasurable" (the
  scorer subprocess dies at import). Do **not** use the `SDK_DIR=/app`
  shortcut: the job image ships only `scripts/`, and the publish hook
  needs `examples/skill_evolution_lab/agent/skill_registry.py` from a
  full SDK clone (`Registry push failed: skill_registry.py not found`).
  The hooks adapter pre-warms the `.sdk/` auto-clone at import so
  concurrent analyst threads never race the clone. If `SDK_DIR` was set
  on the job by an earlier execution, strip it first:
  `gcloud run jobs update bqaa-skill-evolution --remove-env-vars SDK_DIR ...`.
- Scope the quality report or the incumbent/V0 figure is computed over
  every app and the whole default 7d window: `QUALITY_APP_NAME=
  knowledge_supervisor` (BigQuery `root_agent_name`) and
  `EVAL_TIME_PERIOD=1h` (the report runs minutes after the traffic hook
  writes the fresh V0 sessions, so a 1h window isolates them).

Execution (env overrides layered per-execution; the deployed stack logs
its own traffic to BigQuery, so the full loop is: synthetic quality
source → traffic hook against the deployed agents → BigQuery quality
report → evolve → gate → PR → publish hook):

```bash
gcloud run jobs execute bqaa-skill-evolution \
  --project skill-evolution-lab --region us-central1 --wait \
  --update-env-vars "^|^EVOLUTION_HOOKS=eval.skill_evolution_hooks|SDK_REPO=https://github.com/evekhm/BigQuery-Agent-Analytics-SDK.git|SDK_BRANCH=lab-stable|QUALITY_SOURCE=synthetic|TRAFFIC_MODE=deployed|TABLE_ID=agent_events|QUALITY_APP_NAME=knowledge_supervisor|EVAL_TIME_PERIOD=1h|EVAL_QUESTIONS_FILE=eval/data/questions/two_defect_lite.json|MIN_SESSIONS=13|MIN_FAILURES=5|EVOLUTION_TARGET_AGENTS=supervisor|EVOLUTION_CANDIDATES=2|SKILL_EVOLUTION_MODEL_ID=gemini-3.5-flash|EVOLUTION_MODEL_ID=gemini-3.5-flash|EVAL_MODEL_ID=gemini-3.5-flash|MODEL_LOCATION=global|GOOGLE_CLOUD_LOCATION=global"
```

Expected (recorded `sample_runs/lite_deployed`): V0 ≈ 23.1% on the 13q
set, winner ≥ 69.2%, publish gate 10/10, a real PR on
`evekhm/skill-evolution-lab` (recorded run: PR #63), and the publish hook
pushing the winner to the Skill Registry.

### Figures — recorded vs reproduced (2026-09-01, execution bqaa-skill-evolution-vgbcp)

| Leg | Recorded | Reproduced via SDK job |
|---|---|---|
| Evolve set V0 (13q) | 23.1% | 23.1% (6/26, QUALITY_APP_NAME + 1h window) |
| Winner (13q) | 69.2% | 100.0 |
| Publish gate | 10/10 | pass (10 passed, 1 skipped, 1 xfailed, 1 xpassed) |
| PR opened | #63 | #121 |
| Registry publish | yes | yes — supervisor v1 pushed to ks-knowledge-supervisor |

### Figures — migrated deploy path (2026-09-03, execution bqaa-skill-evolution-j4z2m)

Re-validation after this repo's deploy surface moved to the SDK-job
wrapper (`agents/workflow/skill_evolution_agent/deploy.sh` rebuilt the
image via the SDK's deploy.sh, smoke SELF-TEST passed, hook wiring
persisted on the job). Two evolution rounds ran (50 min):

| Leg | Result |
|---|---|
| Evolve set V0 (13q) | 23.1% |
| Round-1 v1 | 26.9% |
| Final eval (winner, 26 sessions) | 100.0% (+73.1pp) |
| Publish gate | pass (10 passed, 1 skipped, 2 xfailed) |
| PR opened | #126 (auto-closes issue #125) |
| Registry publish | yes — supervisor v2 pushed to ks-knowledge-supervisor (revisions: 37) |

Cleanup: delete or pause the weekly scheduler when the lab should not
keep evolving on its own —
`./deploy.sh --down --project skill-evolution-lab --region us-central1`.

---
Disposition (2026-09-01): Scenario 2 reproduced end-to-end (execution
bqaa-skill-evolution-vgbcp; figures above). SDK port shipped as
GoogleCloudPlatform/BigQuery-Agent-Analytics-SDK#472. Follow-ups:
lab issues #122 (score-traffic BigQuery pollution), #123
(default_app_name auto-scoping), #124 (publish-hook unit test); SDK
items in a comment on PR #472.
