# Skill Evolution — Triage Report

**Held-out meaningful rate:** V0 41.8% → V1 67.3%

## Evolution auto-healed 13/17 skill-fixable failures (76.5%)

_10 skill-fixable failure(s) not yet recovered → routed to EVOLUTION (next round)._

## Cannot be fixed by skill evolution → routed backlog (8)

tool bugs: 1 · missing tools: 1 · knowledge gaps: 6 · out-of-scope: 0

### ENG — tool bug / missing tool (2)

- **Q:** How much does the company contribute to my HSA for family coverage?
  - root cause (tool_gap): The existing benefits_agent covers HSA but lacks the specific capability to retrieve detailed contribution amounts based on coverage type (e.g., family coverage).
  - fix: Enhance the benefits_agent to include the functionality to query and provide specific HSA contribution amounts for different coverage types.
  - expected: $1,500/year for family coverage ($750 individual).
  - got: I can only provide information on specific benefits topics. 'HSA family coverage' is not something I can look up directly. If you're trying…
- **Q:** If I make $117,000 and take 8 weeks of short-term disability, what's my total payout?
  - root cause (tool_bug): The agent performed a calculation for short-term disability payout but returned an incorrect numerical value, failing to apply the 60% payout rate correctly.
  - fix: Debug the hr_calculator tool or the calculation logic within the benefits_agent to ensure it correctly applies the percentage payout for short-term disability benefits.
  - expected: $10,800 total ($1,350/week for 8 weeks, within the 12-week max).
  - got: Your total payout for 8 weeks of short-term disability would be $18,000. This amount represents 60% of your regular salary. Short-term disa…

### KNOWLEDGE — add a fact to the knowledge base (6)

- **Q:** What are the core collaboration hours for remote work?
  - root cause (knowledge_gap): The policy_agent is the correct tool for remote work policies, but the specific information about core collaboration hours is missing from its underlying data.
  - fix: Add the core collaboration hours (10am-3pm in the employee's local timezone) to the remote work policy documentation accessible by the policy_agent.
  - expected: 10am-3pm in the employee's local timezone.
  - got: I cannot answer your question about core collaboration hours. Please contact HR for more information.
- **Q:** What's the daily meal reimbursement limit on business travel?
  - root cause (knowledge_gap): The agent correctly identified that the query falls under 'expenses' which the policy_agent handles, but the specific information about meal reimbursement limits was missing from its knowledge base.
  - fix: Add the daily meal reimbursement limit for business travel ($75/day) to the knowledge base or documentation accessible by the policy_agent.
  - expected: $75/day for meals on business travel.
  - got: I do not have information on meal reimbursement limits. Please contact HR for this information.
- **Q:** Are preventive dental cleanings covered?
  - root cause (knowledge_gap): The benefits_agent has a tool for general dental insurance information, but the specific fact about preventive dental cleanings coverage is missing from its accessible knowledge base.
  - fix: Add the specific coverage details for preventive dental cleanings to the benefits_agent's knowledge base so it can directly answer such queries.
  - expected: Yes - preventive dental care is fully covered (80% for major procedures).
  - got: I can only provide information on specific benefits topics. While I can look up general dental insurance information, I don't have the abil…
- **Q:** What's the company 401k match?
  - root cause (knowledge_gap): The agent correctly identified the topic as 401k, which falls under the benefits_agent, but explicitly stated it could not provide the specific detail of the match, indicating the necessary fact is m…
  - fix: Add the company's 401k match percentage to the benefits_agent's knowledge base so it can answer specific queries on this topic.
  - expected: A 4% company 401(k) match.
  - got: I cannot provide specific details on the 401k match. This is a topic that falls under '401k/retirement'. For detailed information, please r…
- **Q:** If I leave after six months, do I keep the 401k match?
  - root cause (knowledge_gap): The benefits_agent was the correct tool for the query, but the specific fact about 401k match vesting periods was missing from its knowledge base, leading it to decline the request.
  - fix: Add the company's 401k match vesting schedule details to the benefits_agent's accessible knowledge base.
  - expected: No - the match is vested only after 1 year, so leaving at 6 months means you don't keep it.
  - got: I cannot help with that. Please contact HR for information on 401k match vesting schedules.
- **Q:** What's the annual tuition reimbursement limit?
  - root cause (knowledge_gap): The question asks for a specific factual detail about tuition reimbursement, which falls under the benefits_agent's domain, but the agent returned an empty response, indicating the specific data poin…
  - fix: Add the annual tuition reimbursement limit (Up to $5,250 per calendar year) to the benefits_agent's knowledge base or data sources.
  - expected: Up to $5,250 per calendar year.
  - got: 

### EVOLUTION — skill failures not yet recovered (10)

- **Q:** Do I need pre-approval for a $600 flight?
  - The agent failed to route an in-scope question about expense policy to the appropriate 'policy_agent' tool, instead declining to answer.
- **Q:** What medical plans are offered?
  - The agent incorrectly identified 'medical plans' as outside its scope, despite explicitly stating it can handle 'health/dental/vision insurance,' which encompasses medical plans.
- **Q:** What's the family out-of-pocket maximum on the PPO?
  - The agent completely misidentified the user's question about PPO benefits as a query about company holidays, leading to an irrelevant and unhelpful response.
- **Q:** What's the individual out-of-pocket maximum on the PPO?
  - The agent failed to parse 'PPO' from the user's question, leading it to incorrectly ask for the plan type again instead of using the benefits_agent to retrieve the information.
- **Q:** What does dental cover for major procedures?
  - The agent has a 'benefits_agent' tool that should cover dental benefits, but it failed to query or extract specific details about major procedure coverage, instead providing a generic disclaimer.
- **Q:** What's the vision benefit for eye exams and glasses?
  - The agent incorrectly stated it could not provide details on specific vision services, despite having a 'benefits_agent' tool designed to handle vision insurance inquiries.
- **Q:** When am I vested in the 401k match?
  - The agent correctly identified the topic as a benefit but failed to directly provide the answer, instead asking for confirmation to look it up.
- **Q:** How early can I start my day under flex time?
  - The agent failed to utilize the 'policy_agent' to answer a question about flex time, which is within its scope, instead declining to answer.
- **Q:** I earn $52,000. What's my total short-term disability payout if I'm out for 4 weeks?
  - The agent had all the necessary policy information (60% of salary) and user-provided data (salary, duration) to perform the requested calculation but failed to do so, instead providing general inform…
- **Q:** I make $65,000 and expect to be out 14 weeks on short-term disability. What's my total benefit?
  - The agent correctly identified the relevant policy details but failed to perform the requested calculation using the provided user input and available tools.
