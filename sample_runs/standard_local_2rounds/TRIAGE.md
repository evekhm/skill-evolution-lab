# Skill Evolution — Triage Report

**Held-out meaningful rate:** V0 36.0% → V1 84.0%

## Evolution auto-healed 8/11 skill-fixable failures (72.7%)

_4 skill-fixable failure(s) not yet recovered → routed to EVOLUTION (next round)._

## Cannot be fixed by skill evolution → routed backlog (0)

tool bugs: 0 · missing tools: 0 · knowledge gaps: 0 · out-of-scope: 0

### EVOLUTION — skill failures not yet recovered (4)

- **Q:** What medical plans are offered?
  - The agent incorrectly stated it could not provide details on health/dental/vision insurance, which is within the scope of the benefits_agent, and then incorrectly suggested referring to the policy_ag…
- **Q:** I earn $52,000. What's my total short-term disability payout if I'm out for 4 weeks?
  - The agent failed to route the short-term disability payout question to the `benefits_agent`, which is designed to handle such inquiries.
- **Q:** On a $91,000 salary, how much does short-term disability pay each week?
  - The agent correctly identified the percentage and calculated the weekly salary but failed to perform the final multiplication to provide the exact weekly short-term disability pay.
- **Q:** What grade do I need for tuition reimbursement?
  - The agent failed to route the question about tuition reimbursement to the appropriate 'benefits_agent', despite having the tool available for this topic.
