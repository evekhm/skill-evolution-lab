# Skill Evolution — Triage Report

**Held-out meaningful rate:** V0 41.8% → V1 65.5%

## Evolution auto-healed 10/17 skill-fixable failures (58.8%)

_16 skill-fixable failure(s) not yet recovered → routed to EVOLUTION (next round)._

## Cannot be fixed by skill evolution → routed backlog (4)

tool bugs: 0 · missing tools: 1 · knowledge gaps: 3 · out-of-scope: 0

### ENG — tool bug / missing tool (1)

- **Q:** What's the individual out-of-pocket maximum on the PPO?
  - root cause (tool_gap): The agent explicitly stated that the `lookup_benefits` tool does not support the topic of 'max out-of-pocket', indicating a missing capability within an existing tool that should cover health benefit…
  - fix: Enhance the `lookup_benefits` tool to include support for querying health plan details such as individual and family out-of-pocket maximums.
  - expected: $4,000 individual in-network ($8,000 family).
  - got: The tool `lookup_benefits` does not support the topic 'max out-of-pocket'. This tool covers health/dental/vision insurance, HSA, orthodonti…

### KNOWLEDGE — add a fact to the knowledge base (3)

- **Q:** What medical plans are offered?
  - root cause (knowledge_gap): The agent correctly identified the topic as benefits but explicitly stated it lacked specific details about the HMO plan, indicating missing information in its knowledge base.
  - fix: Update the benefits agent's knowledge base with comprehensive details regarding the HMO medical plan, including its offerings and specifics.
  - expected: PPO and HMO plans.
  - got: I can only provide information about health insurance, dental insurance, vision insurance, HSA, orthodontia, max out-of-pocket, 401k/retire…
- **Q:** What's the family out-of-pocket maximum on the PPO?
  - root cause (knowledge_gap): The agent correctly identified the question as related to benefits and even suggested contacting the 'Benefits Agent,' but the specific data for the PPO plan's out-of-pocket maximum was not available…
  - fix: Add the PPO plan's family out-of-pocket maximum details to the benefits_agent's knowledge base.
  - expected: $8,000 for a family in-network ($4,000 individual).
  - got: I understand you're asking about the PPO family out-of-pocket maximum. While I can provide information on the general "max out-of-pocket" b…
- **Q:** If I leave after six months, do I keep the 401k match?
  - root cause (knowledge_gap): The agent correctly identified the topic (401k) but explicitly stated it could not provide the specific detail about matching policies after a certain period, indicating the necessary information is …
  - fix: Add the company's 401k match vesting schedule and related policies to the `benefits_agent`'s knowledge base.
  - expected: No - the match is vested only after 1 year, so leaving at 6 months means you don't keep it.
  - got: I can only provide information on 401k/retirement plans, not specific details about matching policies after a certain period of employment.…

### EVOLUTION — skill failures not yet recovered (16)

- **Q:** Do sick days roll over to the next year?
  - The agent failed to provide an answer to a question that falls within the scope of an existing tool (policy_agent) and for which the information should be available.
- **Q:** Do I need approval to work remotely?
  - The agent correctly answered the core question about remote work approval but included an irrelevant statement about not finding information on a system/portal, indicating a slight misinterpretation …
- **Q:** Do I need pre-approval for a $600 flight?
  - The agent failed to retrieve existing information about expense pre-approval from the HR handbook, despite the policy agent being responsible for expense policies and the information being available.
- **Q:** How much does the company contribute to my HSA for family coverage?
  - The supervisor agent failed to properly route the HSA contribution question to the designated 'benefits_agent' tool, which is capable of handling such inquiries, and instead instructed the user to co…
- **Q:** Are preventive dental cleanings covered?
  - The agent had the appropriate tool (benefits_agent) and the knowledge to answer the question about dental cleaning coverage but failed to use it, instead deferring to plan documents.
- **Q:** What does dental cover for major procedures?
  - The agent had access to the benefits tool and the necessary data, but misbehaved by not providing the specific information and instead punted to external documentation.
- **Q:** What's the vision benefit for eye exams and glasses?
  - The assistant incorrectly declined to answer a question about vision benefits, which is explicitly within the scope of the benefits_agent tool.
- **Q:** What's the company 401k match?
  - The agent correctly identified the relevant topic (401k/retirement) and the tool that covers it, but failed to directly answer the specific question about the 401k match, instead asking for rephrasin…
- **Q:** When am I vested in the 401k match?
  - The agent correctly identified the topic as 401k vesting, which falls under the benefits_agent's capabilities, but failed to route the query or provide the information, instead telling the user to co…
- **Q:** How much parental leave does a secondary caregiver get?
  - The agent correctly identified that parental leave falls under company policy but failed to route the request to the `policy_agent` which is designed to handle such queries.
- **Q:** How many bereavement days do I get for a grandparent?
  - The agent has a 'policy_agent' capable of handling bereavement day inquiries, but it failed to route the question correctly and incorrectly stated it could not provide the information.
- **Q:** What grade do I need for tuition reimbursement?
  - The agent correctly identified the relevant specialist agent (benefits_agent) but failed to actually retrieve and provide the answer to the user's question, instead only announcing its intention to r…
- **Q:** What does short-term disability pay?
  - The agent failed to route the question about short-term disability, which is within the scope of the benefits_agent, to the correct tool, resulting in an empty response.
- **Q:** Can I get a work-related course reimbursed, and up to how much?
  - The agent incorrectly declined to answer a question about tuition reimbursement, which is within its capabilities and covered by the benefits_agent, despite acknowledging it could access such informa…
- **Q:** I make $65,000 and expect to be out 14 weeks on short-term disability. What's my total benefit?
  - The agent correctly identified all policy parameters for the calculation but failed to execute the final calculation using the available hr_calculator tool, instead instructing the user to do it.
- **Q:** What's the weekly short-term disability benefit on a $182,000 salary?
  - The supervisor agent correctly identified the need to route to the Benefits Agent but failed to complete the task by actually obtaining and providing the answer to the user.
