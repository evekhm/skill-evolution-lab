# SDK skill-evolution job — lab E2E runbook

How to reproduce this lab's recorded skill-evolution scenarios
(`sample_runs/`) using the **SDK's generic Cloud Run Job port**
(`deploy/skill_evolution_job/` in BigQuery-Agent-Analytics-SDK, branch
`feat/skill-evolution-job`) instead of the lab's own harness. The lab is
wired in exclusively through the job's host-hook seam:
`eval/skill_evolution_hooks.py` (`EVOLUTION_HOOKS=eval.skill_evolution_hooks`)
plus `eval/skill_evolution/sdk_job_requirements.txt` for the image.

The job's engine must be the one this repo pins (`SDK_REPO@SDK_BRANCH`
in `.env`, the `lab-stable` branch): it has the agentic analyst kwargs
`error_analyst_fn`, `tools`, `incumbent_score`, `analyst_timeout_s`. The
job source branch ships upstream main's `scripts/skill_evolution.py`,
which lacks them (SDK PR #395 is still open); on that engine the job
logs the dropped keywords and falls back to single-pass analysts and
size-based candidate selection. Locally, `ensure_sdk.py` clones the pin
to `.sdk/BigQuery-Agent-Analytics-SDK`, so point the job there
(`SDK_SCRIPTS_DIR=$PWD/.sdk/BigQuery-Agent-Analytics-SDK/scripts`). For
the image, `agents/workflow/skill_evolution_agent/deploy.sh` clones the
same pin and passes it to the SDK's `deploy.sh --scripts-dir`.

The job accepts `EVOLUTION_WORKDIR` pointing at a git worktree as well as
a clone (a worktree's `.git` is a file; the PR head rejected it, fixed in
the job's `config.py`).

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
  SDK_SCRIPTS_DIR=$PWD/.sdk/BigQuery-Agent-Analytics-SDK/scripts PYTHONPATH=$PWD
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

### Figures — PR #472 head as shipped, upstream engine (2026-09-04, run `2026-09-03_233649_sdk472_lite_local_upstream_engine`)

Same scenario against the job at SDK PR #472 head (bd534d6) with the
engine the PR ships (upstream main `scripts/skill_evolution.py`,
`SDK_SCRIPTS_DIR` unset) plus the one-line worktree fix in the job's
`config.py`; lab side is this branch. The V0 exam is not re-measured; the
reference from the run above is reused.

| Leg | lab-stable engine (run above) | upstream engine (this run) |
|---|---|---|
| Evolve set V0 (13q, lab judge) | 46.2% (6/13) | 30.8% (4/13) |
| Evolve set V0 re-scored by the engine | not run (`incumbent_score` passed) | 46.2% (kwarg dropped, engine re-ran traffic) |
| Evolve set winner (13q) | 100.0% | 100.0% (both candidates 100.0%) |
| Exam V0 (55q) | 41.8% (23/55) | 41.8% (reference reused) |
| Exam V1 (55q) | 100.0% (55/55) | 100.0% (55/55) |
| Exam delta | +58.2pp | +58.2pp vs reference |
| pr_preview.md | yes | yes (title `30.8% -> 100.0%`, evolved figure from `evolved_score.json`) |

Elapsed: V0 traffic 4.6 min + score 0.9 min; job step 19.7 min (engine's
own V0 re-score 5.7 min, then ~6 min per candidate); exam 19.1 min.

Observed on the upstream engine: the job logs `does not support kwargs
['error_analyst_fn', 'incumbent_score'] — dropping them`, analysts run
single-pass (~30 s for both candidates), and the engine re-scores V0
itself (same 13 questions, live judge: 46.2% against the report's
30.8%), so the incumbent guard uses its own figure, not the report's.
The first attempt failed at the job step with `--mode: invalid choice:
'supervisor'` because `EVOLUTION_WORKDIR` was a git worktree (the
registry never loaded); fixed in the job's `config.py`, and the `--mode`
help now names the registry error.

## Scenario 2 — lite_deployed (full loop in Cloud Run, real PR)

Prerequisites:

- The hooks adapter must be **committed to this repo on GitHub**
  (`evekhm/skill-evolution-lab@main`): the job clones the repo at runtime
  and imports `EVOLUTION_HOOKS` from the clone.
- Image built with the pinned engine and the adapter's dependencies.
  The lab wrapper does the whole thing (clones the job source and the
  engine pin, runs the SDK's `deploy.sh` with `--scripts-dir`,
  `--extra-requirements` and `--smoke`, then persists the lab env on the
  job):

  ```bash
  bash agents/workflow/skill_evolution_agent/deploy.sh
  ```

  It refuses to build when the engine it is about to bake has no
  `error_analyst_fn` (the image would silently lose the agentic
  analysts and the incumbent guard). `--github-repo` + `--gh-secret`
  (derived from `origin` and `GH_SECRET_NAME`) together flip
  `EVOLUTION_PUBLISH=true` on the job — real PR mode. `--agent-registry`
  stays relative on purpose: the job resolves it inside its runtime
  clone of this repo.
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
wrapper (image rebuilt via the SDK's deploy.sh, smoke SELF-TEST passed,
hook wiring persisted on the job). The loop closed (gate, PR, registry
push), 50 min, but the run exposed four defects, all fixed afterwards:

| Leg | Result |
|---|---|
| Evolve set V0 (13q, BigQuery 1h window: 26 sessions) | 23.1% |
| Winner on the evolve set (`evolved_score.json`, incumbent-guarded selection) | 100.0% |
| Post-round BigQuery re-reports `v1_`/`v2_quality_report.json` | 26.9% both, the same 26 sessions: stale, not a measurement of the winner |
| Held-out exam (55q) | not run by the job |
| Publish gate | pass (10 passed, 1 skipped, 2 xfailed) |
| PR opened | #126 (auto-closes issue #125); title reads "23.1% -> 26.9%", the stale figure |
| Registry publish | yes — supervisor v2 pushed to ks-knowledge-supervisor |

Defects found (Cloud Build source and execution log are the evidence):

1. The image carried the lab-stable engine copied over by hand; the
   wrapper as committed clones the job branch fresh and would have baked
   the upstream engine (no agentic analysts, no incumbent guard). Fixed:
   the wrapper clones the engine pin and passes `--scripts-dir`.
2. `EVOLUTION_CANDIDATES=2` was bypassed: the orchestrating agent passed
   `candidates=3` to `run_evolution` and the job honored it. Fixed in the
   job (the env value is binding over the caller's).
3. A second round ran although the profile is one round:
   `EVOLUTION_MAX_ROUNDS` was only enforced for `run_coevolution` and the
   lite profile did not set it. Fixed: per-agent guard on `run_evolution`
   and `EVOLUTION_MAX_ROUNDS=1` in `run_lite.sh`.
4. The PR title/body took the evolved figure from the stale re-report
   instead of the selection score. Fixed: `evolved_score.json` is the
   authoritative evolved figure; `run_quality_report` flags a report whose
   summary is identical to an earlier one as `stale`.

Cleanup: the SDK deploy leaves `bqaa-skill-evolution-cron` ENABLED
(weekly, real-PR mode). Pause it when the lab should not keep evolving
on its own, the way the legacy schedulers are kept:

```bash
gcloud scheduler jobs pause bqaa-skill-evolution-cron \
  --project skill-evolution-lab --location us-central1
```

or tear the job + trigger down with
`./deploy.sh --down --project skill-evolution-lab --region us-central1`
(SDK checkout). The legacy lab resources are still present and paused,
`skill-evolution-weekly` (scheduler) and `skill-evolution-agent` (Cloud
Run job); they are superseded by the SDK job and can be deleted:

```bash
gcloud scheduler jobs delete skill-evolution-weekly \
  --project skill-evolution-lab --location us-central1
gcloud run jobs delete skill-evolution-agent \
  --project skill-evolution-lab --region us-central1
```

---
Disposition (2026-09-01): Scenario 2 reproduced end-to-end (execution
bqaa-skill-evolution-vgbcp; figures above). SDK port shipped as
GoogleCloudPlatform/BigQuery-Agent-Analytics-SDK#472. Follow-ups:
lab issues #122 (score-traffic BigQuery pollution), #123
(default_app_name auto-scoping), #124 (publish-hook unit test); SDK
items in a comment on PR #472.
Disposition (2026-09-04): PR #472 head verified as shipped (upstream
engine, run `2026-09-03_233649_sdk472_lite_local_upstream_engine`,
figures under Scenario 1); fixes pushed to the PR #472 branch
(candidate/round binding, worktree workdir, `--scripts-dir`, stale
re-report flag, PR-title metric source) and to this branch (engine pin in
the deploy wrapper, `EVOLUTION_MAX_ROUNDS=1` in run_lite.sh). Cleanup
commands above are pending the owner's decision.
