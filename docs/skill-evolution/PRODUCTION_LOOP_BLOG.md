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

## The Skill Registry is where the skill lives

New in this iteration: the agents' skills are stored in the Gemini Enterprise
Agent Platform Skill Registry, and the deployed agents read them from there.

At startup, each agent calls GetSkill, unzips the payload, and loads SKILL.md
from it:

```text
Loaded skill from registry ks-policy-agent (revision {{REVISION_SHA}})
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
| Meaningful rate | {{V0_RATE}} | {{V1_RATE}} |
| Corrections held | {{V0_CORR}} | {{V1_CORR}} |

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

{{RESULTS_SECTION: filled from the recorded run — V0 deflections and parroted
corrections with a real trace, V1 behavior on the same questions, final
table.}}

## Limitations we kept

Two SDK issues are open and visible in this demo's wiring. Golden expected
answers reach the judge on the conversations-file path; the BigQuery-path
judge scores against scope and ground truth without per-session goldens
(#358). Trace queries scope rows by session id, so this demo keeps scoring
passes separated by label filters (#359). Both are tracked with an
implementation plan (#361), and the demo's honesty is the better for naming
them.

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
