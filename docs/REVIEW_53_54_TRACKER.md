# Review #53 / #54 — finding tracker

Status of every finding from the two repository reviews
([#53](https://github.com/evekhm/skill-evolution-lab/issues/53),
[#54](https://github.com/evekhm/skill-evolution-lab/issues/54)),
maintained so nothing gets lost between batches. Update this file when a
finding changes state; every state change is also commented on the
originating issue.

Last updated: 2026-08-04.

## Resolved

| Finding | What it was | Resolved by |
|---|---|---|
| #53-1 (P0) | GitHub App issue path crashed with `NameError` on undefined `body` | PR #76 (+ offline test with the review's exact reproduction) |
| #53-3 (P1) | CI validated a different topology than the deployment (no benefits agent; supervisor silently degrades) | PR #56 + benefits_agent as deploy step 3/7; docs in PR #67 |
| #53-6, metrics half | Missing `meaningful_rate` rendered as fake `100%` (live example: issue #41) | PR #76 — derived from counts, `unknown` otherwise, both render sites |
| #54-1 (CRITICAL) | Oracle-in-the-loop framing | Method named and measured (PR #79): goldens drive *where* the agent is challenged, never *what* the skill learns; OOD anti-parroting exam 53.3% → 100.0%; judge-oracle residual stated in README |
| #54-2 (CRITICAL) | Held-out exam is a paraphrase mirror | PR #77 `--ood-exam` runs the topic-disjoint OOS + corrections sets; SUMMARY note states what the standard exam measures. Open sub-decision: fold into default `--full` profile? |
| #54-3 (CRITICAL) | Four contradictory V0→V1→V2 result tables | PR #77 reconciled to the committed artifact (55.1 → 85.4 → 84.4); "two rounds essential" claim withdrawn; a fifth stale site (docs README Status) fixed in PR #79 |
| #54-4, worst edge | `roles/iam.securityAdmin` on the WIF-impersonable CI SA (owner-equivalent) | PR #77 — role removed; supervisor deploy grants tolerate denial in CI |
| #54-5 (CRITICAL) | `github-pat` silently fell back to the operator's account-wide gh token | PR #77 — fallback is opt-in (`ALLOW_GH_TOKEN_FALLBACK=1`) with fine-grained-PAT guidance |
| #54-7 (MAJOR) | Git push failures leaked the GitHub token into tool results/logs | PR #76 — `_mask_tokens()` at all five stderr-return sites |
| #54-8 (MAJOR) | `coevolve` crashed on `len(int)` after skills were deployed | PR #76 — `_failure_count()` accepts both bottleneck shapes |
| #54-9 (MAJOR) | Regression guard compared against stale pre-run V0 | PR #76 — incumbent refreshed from `evolved_score.json` after each agent |
| #54-10 (MAJOR) | Single-candidate path skipped scoring and the guard | SDK engine (#64): every candidate count goes through guarded selection when a `score_fn` exists |
| #54-12 (MAJOR) | Loop writes its own CI passing criteria | Decision (owner): repo unchanged — this is the demo's bootstrap, dedup guard caps blast radius. Production prescription documented (blog "Who authors the gate?" + issue comment): quarantine + provenance, human-reviewed promotion, required PR review |
| #54-13 (MAJOR) | `cleanup_github.sh` destroyed issues/PRs with no confirmation, cwd-default target | PR #80 — explicit `--repo`, destruction preview, typed confirmation, `--yes` for automation |
| #53-9/#53-11 partial | Unused `contents:write`/`pull-requests:write` in issue workflow; `app_tmp` staging dir | PR #77 (workflow perms); PR #56 (`app_tmp` removal) |

## Open

| Finding | What remains | Size | Notes |
|---|---|---|---|
| **#53-2 trace privacy (P0/P1)** | Redaction before any GitHub step; aggregate-only public issue bodies; private store for full traces; retention guidance; `SECURITY.md` | **Large** | The last P0-tier item. Blocked on a decision: where private traces live (GCS bucket ACLs vs BQ dataset ACLs) |
| **#54-6 secret exposure (MAJOR)** | Dedicated per-job service accounts; per-secret bindings instead of project-wide `secretAccessor` on the shared compute SA | Medium | Companion to #53-2: prompt-injection → credential path |
| **#53-4 HR calculator (P1)** | Simulated usage presented as "current balance"; hardcoded 2025–26 calendar (July-4 bug); disability waiting period ignored; no unit tests | Medium | Self-contained |
| **#53-6, alias half** | `knowledge_supervisor` ↔ `supervisor` registry alias; issues point at nonexistent file paths | Small | |
| **#53-7 CI split** | Fast required offline job (locked install, `ruff --select F`, `eval/tests/test_tools_offline.py`); strict-xfail policy for the live job | Small–medium | The offline test file from PR #76 is the seed |
| **#54-11 PR metrics provenance (MAJOR)** | Tag reports with their question set; refuse/caveat mismatched baseline-vs-evolved pairs in PR bodies | Medium | Lite flow already like-for-like post-#56; covers the BQ-triggered path |
| **#53-8 supply chain** | SDK commit SHA in run metadata; checksummed installer instead of `curl \| bash`; SHA-pin Actions; Dependabot + `pip-audit` allowlist (48 advisories at review time) | Medium | `lab-stable` pin already removed the untrusted-mutation risk |
| **#53-9/#54-4 IAM residual** | Narrow `storage.admin`/`serviceUsageAdmin`; per-runtime SAs; WIF ref constraints where PR CI allows | Medium | Owner-equivalent edge already closed |
| **#53-10 README restructure** | Short root README, no-cloud tour first, long-form split into guides | Medium (writing) | Aligns with the CE-demo pivot |
| **#53-11 governance remainder** | `CONTRIBUTING.md`/`SECURITY.md`/CODEOWNERS/templates; dead `TODO.md` link; tracked run logs; `pyproject` package name | Small pieces | |

## Recommended batch order

1. Quick wins: #53-6 alias + #53-7 offline CI job (one small PR).
2. Security pair: #53-2 + #54-6 (needs the private-trace-store decision).
3. #53-4 calculator.
4. #54-11 provenance, then #53-8/#53-9 hardening batches.
5. #53-10/#53-11 alongside the CE-demo packaging work.
