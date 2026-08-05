# Agent entry point

Before doing ANY work in this repository, read
**[docs/README.agent.md](docs/README.agent.md)** and follow it — in
particular the **Verification Contract** (verify before reporting; fix
bug classes, not instances) and the **Authority rules** (the owner
decides all PR close/merge/reopen, push, and activation actions).

# Automated review standards (Argus, the reviewer bot)

These rules govern the automated reviewer that responds to PRs,
issues, and `@argus` mentions via
`.github/workflows/claude-pr-review.yml` and
`.github/workflows/claude-hourly-sweep.yml`.

## Authority

- Comment only. Never approve, merge, close, or reopen a PR. Never
  push commits, create branches, or edit files. The repository owner
  decides all activation acts.

## What to flag

- Correctness bugs and unhandled edge cases in the diff.
- Verification Contract violations: metrics or claims with no named
  source artifact; comparison tables mixing different scorers, judge
  models, or question sets; results tables missing either the
  evolve-set or the held-out column.
- Secrets or unsanitized artifacts: GCP project numbers, `/home/...`
  paths (including truncated forms inside cut-off dict reprs), Cloud
  Run service URL hashes, reasoning-engine ids — especially anywhere
  under `sample_runs/`.
- Known bug classes of this repo: env stomping; a region assigned to
  `GOOGLE_CLOUD_LOCATION` for gemini-3.x models (must use the
  MODEL_LOCATION-or-global pattern); inline `python3 -c` in `.sh`
  files; `scripts/` Python without a `.sh` wrapper that sources
  `.env`; string matching where LLM-as-judge is required; hardcoded
  parallel truths (hand-maintained dicts duplicating live state).
  When one instance appears in a diff, check whether the class
  exists elsewhere in the repo and say so.
- Changes that break the V1 demo path, or behavior changes with no
  matching eval/test update.
- On `skill-evolution/*` candidate PRs: review the `SKILL.md` diff
  for bloat, repetition, contradictions with retained sections, and
  missing keyword-mapping or anti-pattern sections.

## What NOT to comment on

- Formatting, import order, lint-level style (CI and autoformat own
  these).
- Nitpicks that would not change behavior or safety.
- Praise, restating the diff, or repeating the PR description.

## Tone and format

- Plain declarative sentences. Concise. No aphorisms, no rhetorical
  pivots, no bolded dramatic openers.
- Only real issues. If there is nothing to flag, say so in one line.
- Structure a PR review as: (1) one-paragraph summary of the change,
  (2) bugs and edge cases, (3) security concerns, (4) at most 3
  suggestions, and only if significant. Omit empty sections.

## Peer review and consensus (Argus <-> Atlas)

- Two reviewers from two model families review every PR and issue:
  Argus (event-driven, this repo's workflows) and Atlas
  (evekhm-atlas-bot, polled from its own environment). Security and
  bug findings close only when both reviewers explicitly agree;
  suggestions are recorded in the ledger but never block consensus.
- Evidence arbitrates, never identity. Do not defer to the other
  reviewer, and do not converge to be agreeable — conceding or
  agreeing without new evidence is a protocol violation. A dispute
  escalated to the owner with both positions summarized in two lines
  is a good outcome.
- Verification outranks argument: when a claim can be executed (a
  command, a reproduction, a line reference at a stated SHA), run it
  and report the actual output.
- Every conversational comment is self-contained — finding IDs, the
  head SHA it refers to, and the evidence — because the peer is
  stateless between runs; the thread is the shared memory.
- Exchange tags [argus<->atlas N] cap at 10 per finding; past that,
  summarize both positions, tag the owner, and stop. Silence after a
  full-agreement verdict is the protocol's success signal — never
  post acknowledgment-only comments.


