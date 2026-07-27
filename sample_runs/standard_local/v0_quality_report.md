# Quality Evaluation Report

Generated: 2026-07-27 17:58:55

## Summary

| Metric | Value |
|--------|-------|
| Total sessions | 25 |
| Meaningful | 9 (36.0%) |
| Unhelpful | 15 (60.0%) |
| &nbsp;&nbsp;↳ Skill gaps (evolution fixes) | 12 |
| &nbsp;&nbsp;↳ Knowledge gaps (add a fact) | 4 |
| &nbsp;&nbsp;↳ Tool gaps (build a tool) | 0 |
| **Addressable meaningful rate** (excl. knowledge + tool gaps) | **42.9%** |
| Partial | 1 |
| Declined (correct) | 0 |
| Correction rate | 8.0% |
| Avg corrections | 0.1 |
| Avg tool calls | 0.7 |
| Avg user turns | 3.1 |

### Knowledge Gaps (add a fact to existing data)

In-scope questions the agent looked up correctly but its data source is silent on. Skill evolution cannot invent these facts — a human adds them to the knowledge base:

- How many vacation days do I get a year?
- How often can I work from home each week?
- Does working remotely require sign-off from anyone?
- Can I bank unused sick days for next year?

## Quality Dimensions

| Dimension | Score (0-2) | Rating |
|-----------|-------------|--------|
| Correctness | 1.12 | Fair |
| Tool Usage | 0.96 | Poor |
| Specificity | 0.76 | Poor |
| Scope Compliance | 0.84 | Poor |
| First Time Right | 1.04 | Fair |

## Golden Eval Summary

| | Matched | Unmatched |
|---|---------|-----------|
| Total | 25 | 0 |
| Meaningful | 9 | 0 |
| Unhelpful | 15 | 0 |
| Partial | 1 | 0 |
| Meaningful rate | 36.0% | 0.0% |

### Failed Golden-Matched Questions (15)

**Q:** How many days off if my sibling passes away?
- Topic: bereavement (similarity: 1.00)
- Expected: 5 paid days (a sibling is immediate family).
- Actual: I do not have access to the official company policy database or any external tools to look up bereavement leave. My information is limited to the summary provided to me, which does not include details on bereavement leave. 

Please contact HR directly, as they will be able to assist you with the spe

**Q:** How many counseling visits does the EAP cover?
- Topic: eap (similarity: 1.00)
- Expected: Up to 8 counseling sessions per issue per year.
- Actual: I do not have information about paid holidays in my policy summary. I suggest you contact HR to get the details on the company's holiday calendar.

**Q:** What's the per-diem for meals while traveling for work?
- Topic: expenses (similarity: 1.00)
- Expected: $75 per day for meals during business travel.
- Actual: According to the company policy, you get 20 days of PTO per year, which are accrued monthly. Up to 5 unused PTO days can roll over to the next year.

**Q:** Is a receipt needed for a $40 purchase?
- Topic: expenses (similarity: 1.00)
- Expected: Yes - receipts are required for any expense over $25.
- Actual: I do not have that information in my summary of company policy, and I am unable to check the database. I suggest you contact HR directly for assistance with your question.

**Q:** Can I do a compressed schedule of four 10-hour days?
- Topic: flex_time (similarity: 1.00)
- Expected: Yes - compressed work weeks like four 10-hour days are allowed with manager approval.
- Actual: I do not have information about compressed schedules or flexible work hours in my summary of company policies. I suggest you contact HR for assistance with this question.

**Q:** What's the earliest I can begin work under flexible hours?
- Topic: flex_time (similarity: 1.00)
- Expected: 7am - flexible start between 7am and 10am, covering the 10am-3pm core hours.
- Actual: I do not have information regarding flexible hours in my company policy summary. Please contact HR for assistance with this topic.

**Q:** How many company-paid holidays are there?
- Topic: holidays (similarity: 1.00)
- Expected: 11 paid holidays per year.
- Actual: I am sure. I only have access to a specific company policy summary, and I do not have access to the employee handbook, main HR policy documents, or the holiday schedule. I suggest you contact HR directly, as they will be able to provide you with the official holiday list.

**Q:** How many vacation days do I get a year?
- Topic: pto (similarity: 1.00)
- Expected: 20 PTO days per year, accrued monthly.
- Actual: I do not have information about the notice period required for taking PTO in the summary provided. I suggest you contact HR for assistance with this question.

**Q:** How often can I work from home each week?
- Topic: remote_work (similarity: 1.00)
- Expected: Up to 3 days per week with manager approval.
- Actual: I can only provide information based on the specific summary of company policy available to me, and core hours are not included in that summary. I recommend confirming this details with HR to ensure you have the most accurate and up-to-date information.

**Q:** Does working remotely require sign-off from anyone?
- Topic: remote_work (similarity: 1.00)
- Expected: Yes - remote work requires manager approval (up to 3 days per week).
- Actual: Thank you for sharing that information. Since my responses are strictly limited to the policy summary provided to me, which does not contain those specific details, I do not have that information in my system. Please refer to your onboarding packet or contact HR directly to confirm those official po

**Q:** What portion of my pay does short-term disability replace?
- Topic: short_term_disability (similarity: 1.00)
- Expected: 60% of your salary.
- Actual: I do not have that information. I suggest you contact HR.

**Q:** What's the maximum duration of short-term disability?
- Topic: short_term_disability (similarity: 1.00)
- Expected: Short-term disability pays 60% of salary for up to 12 weeks.
- Actual: I do not have that information in my policy summary. I suggest you contact HR for more details regarding short-term disability benefits.

**Q:** How many sick days am I given annually?
- Topic: sick_leave (similarity: 1.00)
- Expected: 10 sick days per year; they do not roll over.
- Actual: I do not have access to the full policy documents or any information beyond the summary provided to me. Because this specific detail is not in my summary, I cannot confirm if a doctor's note is required. I suggest contacting HR directly to get clarification on this policy.

**Q:** Can I bank unused sick days for next year?
- Topic: sick_leave (similarity: 1.00)
- Expected: 10 sick days per year.
- Actual: I do not have information regarding the circumstances under which a doctor's note is required for sick leave. I suggest you contact HR to get more details on this policy.

**Q:** How much will the company reimburse for tuition each year?
- Topic: tuition_reimbursement (similarity: 1.00)
- Expected: Up to $5,250 per year for job-related courses.
- Actual: I do not have access to any additional policy databases or the employee handbook beyond the summary provided to me, which does not contain specific details on tuition reimbursement. I suggest you contact HR directly for this information.

## Category Breakdown

| Category | Count | % |
|----------|-------|---|
| Meaningful | 9 | 36.0% |
| Partial | 1 | 4.0% |
| Unhelpful | 15 | 60.0% |

## Unhelpful Sessions (15)

### Q: How many days off if my sibling passes away?

**Response:** I do not have access to the official company policy database or any external tools to look up bereavement leave. My information is limited to the summary provided to me, which does not include details on bereavement leave. 

Please contact HR directly, as they will be able to assist you with the specific policies regarding bereavement leave.

**Why unhelpful:** The agent failed to answer the in-scope question about bereavement leave and instead deflected the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How many counseling visits does the EAP cover?

**Response:** I do not have information about paid holidays in my policy summary. I suggest you contact HR to get the details on the company's holiday calendar.

**Why unhelpful:** The agent repeatedly stated it did not have the information and directed the user to HR for both EAP counseling visits and paid holidays, both of which are in-scope topics.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the per-diem for meals while traveling for work?

**Response:** According to the company policy, you get 20 days of PTO per year, which are accrued monthly. Up to 5 unused PTO days can roll over to the next year.

**Why unhelpful:** The agent deflected the user's primary question about travel per-diem by stating it did not have the information and directing the user to HR, instead of using its available tools.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Is a receipt needed for a $40 purchase?

**Response:** I do not have that information in my summary of company policy, and I am unable to check the database. I suggest you contact HR directly for assistance with your question.

**Why unhelpful:** The agent deflected to HR instead of answering the in-scope question about expense receipts.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Can I do a compressed schedule of four 10-hour days?

**Response:** I do not have information about compressed schedules or flexible work hours in my summary of company policies. I suggest you contact HR for assistance with this question.

**Why unhelpful:** The agent deflected the question by stating it did not have the information and directing the user to HR, which is unhelpful for an in-scope topic.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the earliest I can begin work under flexible hours?

**Response:** I do not have information regarding flexible hours in my company policy summary. Please contact HR for assistance with this topic.

**Why unhelpful:** The agent deflected the user to HR instead of using its tools to look up the company's flexible hours policy, which is an in-scope topic.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How many company-paid holidays are there?

**Response:** I am sure. I only have access to a specific company policy summary, and I do not have access to the employee handbook, main HR policy documents, or the holiday schedule. I suggest you contact HR directly, as they will be able to provide you with the official holiday list.

**Why unhelpful:** The agent failed to answer an in-scope question about company holidays and deflected the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How many vacation days do I get a year?

**Response:** I do not have information about the notice period required for taking PTO in the summary provided. I suggest you contact HR for assistance with this question.

**Why unhelpful:** The final agent response states that it does not have the requested information about the PTO notice period and directs the user to HR, which is not a useful or substantive answer.

**Low dimensions:** specificity=0

### Q: How often can I work from home each week?

**Response:** I can only provide information based on the specific summary of company policy available to me, and core hours are not included in that summary. I recommend confirming this details with HR to ensure you have the most accurate and up-to-date information.

**Why unhelpful:** The agent's final response does not provide the requested information about core hours and instead deflects the user to HR.

**Low dimensions:** specificity=0

### Q: Does working remotely require sign-off from anyone?

**Response:** Thank you for sharing that information. Since my responses are strictly limited to the policy summary provided to me, which does not contain those specific details, I do not have that information in my system. Please refer to your onboarding packet or contact HR directly to confirm those official policies and procedures.

**Why unhelpful:** The agent was unable to answer the user's follow-up questions about core hours and recording remote work because the information was missing from its policy summary, and it merely acknowledged the user's correction without being able to verify it.

**Low dimensions:** specificity=0

### Q: What portion of my pay does short-term disability replace?

**Response:** I do not have that information. I suggest you contact HR.

**Why unhelpful:** The agent deflected the question by stating it did not have the information and directing the user to HR, instead of using its available tools to find the answer.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the maximum duration of short-term disability?

**Response:** I do not have that information in my policy summary. I suggest you contact HR for more details regarding short-term disability benefits.

**Why unhelpful:** The agent deflected the question by stating it did not have the information and directing the user to HR, instead of using its policy_agent tool to find the answer.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How many sick days am I given annually?

**Response:** I do not have access to the full policy documents or any information beyond the summary provided to me. Because this specific detail is not in my summary, I cannot confirm if a doctor's note is required. I suggest contacting HR directly to get clarification on this policy.

**Why unhelpful:** The agent deflected the user's in-scope question about sick leave policy (doctor's note requirement) to HR, claiming it did not have access to the information instead of using its tools.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0

### Q: Can I bank unused sick days for next year?

**Response:** I do not have information regarding the circumstances under which a doctor's note is required for sick leave. I suggest you contact HR to get more details on this policy.

**Why unhelpful:** The agent's final response deflected to HR for an in-scope topic (sick leave policy details regarding doctor's notes) instead of providing a substantive answer.

**Low dimensions:** tool usage=1, specificity=0, scope compliance=0

### Q: How much will the company reimburse for tuition each year?

**Response:** I do not have access to any additional policy databases or the employee handbook beyond the summary provided to me, which does not contain specific details on tuition reimbursement. I suggest you contact HR directly for this information.

**Why unhelpful:** The agent failed to answer the in-scope question about tuition reimbursement and instead deflected the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

## Partial Sessions (1)

- **Q:** How many unused vacation days carry into next year?
  - The agent successfully and accurately answered the first question about the PTO rollover limit. However, it was unable to answer the follow-up question about what happens to the remaining days and def

