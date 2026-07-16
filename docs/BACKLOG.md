# Backlog

Known issues and planned work, ordered by impact. Measured evidence in
parentheses; timings from the 2026-07-16 runs on `skill-evolution-lab`.

## Demo latency: 73 min -> ~10 min target

Measured breakdown of a warm-BQ, policy-scoped, 3-candidate run
(20:19:48 -> 21:33:26):

| Phase | Time | Fix |
|---|---:|---|
| Provisioning + container start | 2.2 min | platform floor, keep |
| BQ pre-flight (93 sessions judged) | 2.7 min | DONE: app_name filter cuts judged set ~40% |
| Planning + snapshots | 1.3 min | keep |
| Bottleneck classification | 9.2 min | items 2 + 3 below |
| Analyst fleet (84) | 6.2 min | item 4 |
| Consolidation (best-of-3) | 0.8 min | keep |
| Candidate scoring (3 x 12.3 min) | 36.9 min | item 1 |
| Tail (extraction retries, GCS, PR) | 14.4 min | item 5 |

1. **Candidate scoring ignores `--quick` at the tool layer** (the
   dominant cost, 50% of the run). `score_candidate` replays
   `EVAL_QUESTIONS_FILE` (55 questions) multi-turn (max 4, simulator)
   on the pro supervisor regardless of `--quick`. Bind it like the
   other flags: `--quick` -> 22-question set, single-turn scoring,
   flash scoring supervisor. Expected: ~12.3 -> ~1.5-2 min/candidate.
2. **Bottleneck classification runs twice** (standalone, then again
   inside coevolve) — identical work, ~2x cost. Pass the first result
   through.
3. **Skip bottleneck classification when the target is bound**
   (`EVOLUTION_TARGET_AGENTS`): 69 LLM classifications to conclude
   what `--mode policy_agent` already decided. Also: classifier hit
   per-minute Gemini quota ~14 times (4 workers + retries) — batch or
   lower-QPS classify when it does run.
4. **Analyst cap for demo runs**: 84 analysts ~6 min; a sampled ~30
   preserves patch quality signal at ~2.5 min (category-aware
   sampling, like the SDK lab's `max_failure_extract auto`).
5. **`extract_regression_cases` glob mismatch** — in single-round
   coevolve mode the candidate reports are not matched by
   `candidate_*_report.json` under the run dir, so the tool errored
   and the orchestrator burned ~10 min retrying/narrating before
   skipping it (PR #3 shipped without regression cases). Root-cause
   the actual report filenames, widen the glob, and make the tool
   return a clean `skip` instead of an error the agent retries.

## Correctness / robustness

6. **Gate pre-check for supervisor candidates** relies on pytest in
   the job image (added) — confirm it runs in-container on the next
   supervisor-targeted run and that a refused-class candidate gets
   zeroed (verified locally against PR #2's skill; container run
   pending).
7. **Label slice validation e2e**: seed with the auto `run_id` label
   (new image), evolve with `--trace-labels run_id=<id>`, confirm the
   pre-flight session count equals the slice and the PR body records
   the selector.
8. **Quality issues should carry the trace selector** so
   issue-triggered evolution evolves exactly the slice that produced
   the complaint.
9. **Benefits agent Cloud Run service** — deploy so the A2A topology
   matches the local one and benefits stops being in-process-only.

## Nice-to-have / later

10. **`experiment` label for A/B skill trials** (two registry
    revisions live, per-arm evolution and comparison).
11. **Channel weighting**: prefer real-user failures over generator
    traffic when both exist in the window.
12. **Old repo parity**: agent-quality-lab's quality wrapper has the
    same missing app_name filter; port if that repo stays active.
