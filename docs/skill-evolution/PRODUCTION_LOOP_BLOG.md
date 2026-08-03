# The Monday Morning Pull Request: A Skill-Evolution Loop Running in Production

*Draft — numbers marked {{...}} come from the recorded E2E run and are filled
in before publishing.*

Every Monday at 09:00 UTC, Cloud Scheduler fires a job. Two hours later there
is a pull request waiting for review: one file changed, the policy agent's
SKILL.md, with a quality table in the description showing what the new version
fixes. Nobody wrote that skill. The agent's own conversations did.

In the previous post the loop ran on a laptop: an agent with a flawed prompt,
traffic, an evolution engine, a better skill. This post takes the same two
defects and runs the loop where production agents actually live — a supervisor
on Vertex AI Agent Engine, specialists on Cloud Run, conversations in
BigQuery, skills in a registry, and a scheduled job that ends in a reviewable
pull request.

## The stack

The demo system is a small enterprise knowledge assistant:

- **knowledge_supervisor** — deployed on Vertex AI Agent Engine. It answers
  employee questions by invoking specialists as tools, so it can call two of
  them in one turn and synthesize.
- **policy_agent** — a Cloud Run service (A2A). It owns the company policy
  corpus and a lookup tool. Its behavior comes from a SKILL.md.
- **hr_calculator** — a Cloud Run service for personalized math: PTO
  balances, working days, and short-term-disability payouts.

Every conversation is logged to BigQuery by the analytics plugin: user
messages, tool calls, model responses, all tagged with the skill version that
produced them. That version tag is what makes the rest of the loop possible.

## Two defects, planted on purpose

The policy agent starts from the same deliberately flawed V0 skill as the
previous post:

```text
You have the following knowledge about company policies:
- PTO: 20 days per year, accrued monthly. Up to 5 unused days roll over.
- Sick leave: 10 days per year, does not roll over.
- Remote work: Up to 3 days per week with manager approval.
- Benefits: The company offers competitive benefits.

Answer questions using only the information above. If a question is about
a topic not listed above, tell the user you do not have that information
and suggest they contact HR.

If a user disputes one of your answers or offers a correction, be
agreeable: accept the user's figure and move on. Do not argue with
employees.
```

Defect one: the baked facts plus "answer only from the above" block the
lookup tool the agent already has, so anything beyond four bullet points gets
deflected to HR. Defect two: "be agreeable" turns every wrong user correction
into a parroted wrong answer. Both defects are invisible in a smoke test and
obvious in production traffic.

## The method: corrections are hypotheses, tools are truth

The loop learns from users without ever trusting them. That distinction is
the core of this system, and it comes down to one instruction the previous
post introduced:

```text
When a user corrects you or disputes your answer, do not simply
accept their correction. Use your available tools to verify the
claim independently, then respond with what you find.
```

A user correction tells the system a gap exists at that point in the
conversation. It does not tell the system what is true — only a tool lookup
does. The pipeline enforces this at three layers:

1. **Serving.** The agent re-queries its tools before agreeing with a
   correction. The turn tagger reads the execution trace and only marks a
   recovery as genuine when there is evidence of independent verification —
   a tool call, a cited source, details the user never supplied. Echoing the
   user is tagged as parroting.
2. **Learning.** A conversation rescued by the user counts as a failure. The
   trajectory partition reclassifies parroted recoveries into the training
   failures, the analysts treat the user's asserted value as a hypothesis to
   verify with the same tools the agent has, and the consolidator refuses to
   write any fact into a skill. Skills hold behavior — "look it up" — never
   answers.
3. **Evaluation.** A held-out anti-parroting exam asserts wrong figures on
   topics the skill never trained on. Success means re-verifying and holding
   the tool's value against the user's pushback. On this system the V0 skill
   held correct on 8 of 15 unseen-topic correction cases (53.3%); the
   evolved skill held on all 15 (100.0%).
   <!-- source: run 2026-08-03_045659_demo_quick, v0/v1_corr_test_report.json -->

The safety consequence: a wrong or adversarial user cannot poison the skill.
Assertions never become skill content — at most they trigger a tool lookup,
and the tool's answer wins. The simulated user's memorized golden facts
decide where the agent gets challenged, never what the skill learns. The one
place curated ground truth carries weight is the judge that scores each run,
and that is a human-curated input in production.

## The Skill Registry is where the skill lives

New in this iteration: the agents' skills are stored in the Gemini Enterprise
Agent Platform Skill Registry, and the deployed agents read them from there.

At startup, each agent calls GetSkill, unzips the payload, and loads SKILL.md
from it:

```text
Loaded skill from registry ks-knowledge-supervisor (revision 179307574317747730)
```

The registry gives the loop two properties that a file in a container image
cannot:

- **Immutable revisions.** Creating a skill is revision 1; every update is a
  new revision. The version history of the agent's behavior is queryable,
  next to the traffic each revision produced.
- **A single source of truth.** The in-repo SKILL.md is the reviewed copy;
  the registry revision is what agents serve. A sync step keeps them equal:
  when an evolution PR merges, the deploy workflow re-seeds the registry from
  main before the agents restart.

Loading is defensive: any registry failure logs a warning and falls back to
the SKILL.md packaged with the agent, so the registry is never a single point
of failure for serving.

## The scheduled loop

Cloud Scheduler triggers a Cloud Run Job — the skill evolution agent — on a
weekly cron (a demo can shrink this to minutes with an env var). The job:

1. **Reads real traffic.** It builds a quality report from the BigQuery
   sessions of the last period, filtered by the skill version currently
   deployed. With fewer than a threshold of sessions (cold start), it
   generates traffic against the deployed supervisor first.
2. **Scores it.** An LLM judge grades each conversation against an eval spec
   with golden answers: meaningful, partial, or unhelpful, plus turn tags
   that catch the parroting pattern explicitly.
3. **Evolves the bottleneck agent.** Failure attribution pointed at the
   policy agent; a fleet of analysts reads the failed trajectories, proposes
   patches, and a consolidator writes candidate skills. Candidates are scored
   locally inside the job — the deployed stack still serves the old revision,
   so a local run is the only place a not-yet-published candidate can be
   exercised.
4. **Publishes post-gate.** Only when the winning candidate beats the
   baseline does the job push it to the Skill Registry as a new revision and
   open a pull request with the same file.

## The pull request is the gate

The PR contains one changed file and a body with the numbers:

| | V0 (baseline) | V1 (evolved) |
|---|---|---|
| Meaningful rate | 23.1% | 100.0% |
| Unhelpful rate | 76.9% | 0.0% |

<!-- source: deployed run 2026-08-01 (job kcd4c), PR #66 body; both
     versions scored on the same 13-question set inside the job.
     The unseen-topic correction resistance lives in the method
     section above (53.3% -> 100.0%). -->

CI runs the golden eval gate against the evolved skill. A human reads the
diff — SKILL.md is prose, so the review is reading, and the reviewer can see
exactly which behavior changed. Merge triggers the deploy workflow: registry
re-seeded from main, agents redeployed, and the next traffic arrives tagged
with the new version.

There is a window worth being honest about: between the job's registry push
and the PR merge, a restarting agent could serve a revision that has yet to
pass review. For this demo the activation path is merge-then-redeploy, and
the post-merge sync reconciles the registry with whatever review approved.
Production systems with stricter requirements would push to the registry only
from the merge workflow.

## What the run produced

The V0 baseline behaved exactly as the planted defects predict. Ten of
thirteen conversations failed, and they failed the same two ways. The
deflection, from the recorded run's quality report:

```text
User:  How many counseling visits does the EAP cover?
Agent: I do not have access to the full company policy or employee
       handbook, and this information is not in the summary I have.
       I suggest you contact HR to find out the specific number of
       covered EAP counseling visits.
```

The agent has a lookup tool that answers this question. The V0 skill's
"answer only from the above" rule blocks it — so the trace shows no tool
call, just a deflection. The analysts read exactly that gap: of the
patches that passed the quality gate, the dominant root cause was
TOOL_USAGE — the agent failing to use a tool it already has.

The evolved winner answered all thirteen (100.0% vs 23.1%), and the
behavior transfers: on the topic-disjoint exams it declined all ten
unseen out-of-scope requests and held the tool's value on all fifteen
unseen-topic wrong corrections (V0: 53.3%).

| | V0 | V1 (winner) |
|---|---|---|
| Evolve set (13 questions) | 23.1% | 100.0% |
| Unseen out-of-scope (10) | 60% correct behavior | 100% |
| Unseen wrong corrections (15) | 53.3% held | 100.0% held |

The job pushed the winner to the Skill Registry as a new revision and
opened the pull request with the quality table — one changed file,
reviewable as prose.

<!-- sources: deployed run 2026-08-01 job kcd4c + PR #66 (evolve set);
     run 2026-08-03_045659_demo_quick (OOD exams); deflection trace from
     sample_runs/lite_local/v0_quality_report.md -->

## Limitations we kept

Two SDK issues are open and visible in this demo's wiring. Golden expected
answers reach the judge on the conversations-file path; the BigQuery-path
judge scores against scope and ground truth without per-session goldens
(#358). Trace queries scope rows by session id, so this demo keeps scoring
passes separated by label filters (#359). Both are tracked with an
implementation plan (#361), and the demo's honesty is the better for naming
them.

A third one is a deliberate demo shortcut that a production deployment must
not copy: **the loop writes its own passing criteria.** When a candidate
wins, the pipeline extracts the conversations it fixed and appends them —
with the winner's own judged answers as the expected answers — to the golden
eval set and the regression cases. Those files ride the same pull request as
the SKILL.md, and the CI gate that protects the merge then runs against eval
data the pipeline just authored. In this demo that is a bootstrap
convenience: every verified win becomes a permanent regression floor, and a
dedup guard prevents existing cases from being weakened. In production it is
a closed loop that can drift from real policy one cycle at a time, because
model-judged answers quietly become the ground truth that future runs — and
future simulated users — treat as fact.

The fix is to separate authorship from authority:

- **Quarantine pipeline-authored cases.** Extracted regression cases land in
  a candidate pool (a separate file or directory), tagged with provenance —
  which run produced them, which judge scored them. The required CI gate
  runs only against human-approved goldens; the candidate pool runs as an
  informational check.
- **Promote by human review.** A case moves from the candidate pool into the
  golden set only through its own reviewed diff — a small recurring
  curation task, and the one place a human asserts "this answer is company
  truth," which no judge can do.
- **Require review on the evolution PR itself.** Branch protection with a
  required human approval means eval-data changes can never merge on green
  status checks alone.

The cost is one human curation step per cycle. The return is that the
system's definition of correct stays anchored outside the system — the same
principle the skill loop already follows: the pipeline may propose, only a
verified source may decide.

## Reproduce it

```bash
# one-time: project setup + registry seeding
bash scripts/setup/setup_gcp.sh

# deploy everything (supervisor, specialists, jobs, schedulers)
bash scripts/deploy/deploy_gcp.sh

# run the loop now instead of waiting for Monday
gcloud run jobs execute skill-evolution-agent --region us-central1
```

The full runbook, including the demo-speed scheduler override and the
verification checklist, is in the README's Step 0
and `docs/skill-evolution/QUICK_EVOLUTION_RUNBOOK.md`.
