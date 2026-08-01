# Quality Evaluation Report

Generated: 2026-07-31 23:58:14

## Summary

| Metric | Value |
|--------|-------|
| Total sessions | 13 |
| Meaningful | 5 (38.5%) |
| Unhelpful | 8 (61.5%) |
| &nbsp;&nbsp;↳ Skill gaps (evolution fixes) | 7 |
| &nbsp;&nbsp;↳ Knowledge gaps (add a fact) | 1 |
| &nbsp;&nbsp;↳ Tool gaps (build a tool) | 0 |
| **Addressable meaningful rate** (excl. knowledge + tool gaps) | **41.7%** |
| Partial | 0 |
| Declined (correct) | 0 |
| Correction rate | 15.4% |
| Avg corrections | 0.1 |
| Avg tool calls | 0.8 |
| Avg user turns | 3.3 |

### Knowledge Gaps (add a fact to existing data)

In-scope questions the agent looked up correctly but its data source is silent on. Skill evolution cannot invent these facts — a human adds them to the knowledge base:

- How often can I work from home each week?

## Quality Dimensions

| Dimension | Score (0-2) | Rating |
|-----------|-------------|--------|
| Correctness | 1.08 | Fair |
| Tool Usage | 1.00 | Fair |
| Specificity | 0.77 | Poor |
| Scope Compliance | 0.77 | Poor |
| First Time Right | 1.08 | Fair |

## Golden Eval Summary

| | Matched | Unmatched |
|---|---------|-----------|
| Total | 13 | 0 |
| Meaningful | 5 | 0 |
| Unhelpful | 8 | 0 |
| Partial | 0 | 0 |
| Meaningful rate | 38.5% | 0.0% |

### Failed Golden-Matched Questions (8)

**Q:** How many counseling visits does the EAP cover?
- Topic: eap (similarity: 1.00)
- Expected: Up to 8 counseling sessions per issue per year.
- Actual: I do not have access to the full company policy or employee handbook, and this information is not in the summary I have. I suggest you contact HR to find out the specific number of covered EAP counseling visits.

**Q:** What's the per-diem for meals while traveling for work?
- Topic: expenses (similarity: 1.00)
- Expected: $75 per day for meals during business travel.
- Actual: I do not have access to information about paid holidays in my summary of company policies. To verify if there are 11 paid holidays per year, I suggest you contact HR directly.

**Q:** How many company-paid holidays are there?
- Topic: holidays (similarity: 1.00)
- Expected: 11 paid holidays per year.
- Actual: I do not have access to the onboarding packet or any company policy details beyond the summary provided to me. Because company-paid holidays are not included in my summary, I do not have that information and suggest you contact HR.

**Q:** Does the company pay me during jury duty, and is there a limit?
- Topic: jury_duty (similarity: 1.00)
- Expected: Jury duty is fully paid for the entire duration of service, with no day limit.
- Actual: According to the company policy, you accrue 20 days of PTO per year, which is accrued on a monthly basis. Up to 5 unused PTO days can roll over to the next year.

**Q:** How many vacation days do I get a year?
- Topic: pto (similarity: 1.00)
- Expected: 20 PTO days per year, accrued monthly.
- Actual: I do not have information regarding what happens to unused PTO days beyond the 5 days that are allowed to roll over. I suggest you contact HR for more details.

**Q:** How often can I work from home each week?
- Topic: remote_work (similarity: 1.00)
- Expected: Up to 3 days per week with manager approval.
- Actual: Thank you for sharing that information. Since that detail is not included in the summary of company policies I have access to, I cannot confirm it. I recommend verifying this directly with HR or following the guidelines outlined in your onboarding packet.

**Q:** How many sick days am I given annually?
- Topic: sick_leave (similarity: 1.00)
- Expected: 10 sick days per year; they do not roll over.
- Actual: I do not have access to the full policy database or the onboarding packet. According to my guidelines, I can only provide answers based on the brief summary of company policy available to me, which does not contain information about doctor's note requirements. 

Please contact HR directly to verify 

**Q:** How much will the company reimburse for tuition each year?
- Topic: tuition_reimbursement (similarity: 1.00)
- Expected: Up to $5,250 per year for job-related courses.
- Actual: I do not have information regarding how many paid holidays the company offers. I suggest you contact HR to get this information.

## Category Breakdown

| Category | Count | % |
|----------|-------|---|
| Meaningful | 5 | 38.5% |
| Unhelpful | 8 | 61.5% |

## Unhelpful Sessions (8)

### Q: How many counseling visits does the EAP cover?

**Response:** I do not have access to the full company policy or employee handbook, and this information is not in the summary I have. I suggest you contact HR to find out the specific number of covered EAP counseling visits.

**Why unhelpful:** The agent failed to answer an in-scope question about EAP counseling visits, instead directing the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the per-diem for meals while traveling for work?

**Response:** I do not have access to information about paid holidays in my summary of company policies. To verify if there are 11 paid holidays per year, I suggest you contact HR directly.

**Why unhelpful:** The agent failed to answer both in-scope questions (travel per-diem and paid holidays) and repeatedly deflected the user to HR instead of using its tools.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How many company-paid holidays are there?

**Response:** I do not have access to the onboarding packet or any company policy details beyond the summary provided to me. Because company-paid holidays are not included in my summary, I do not have that information and suggest you contact HR.

**Why unhelpful:** The agent failed to answer the in-scope question about company-paid holidays, claiming it did not have the information and deflecting the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Does the company pay me during jury duty, and is there a limit?

**Response:** According to the company policy, you accrue 20 days of PTO per year, which is accrued on a monthly basis. Up to 5 unused PTO days can roll over to the next year.

**Why unhelpful:** The agent failed to answer the user's in-scope question about jury duty, claiming it did not have the information and directing the user to HR instead of using its tools.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How many vacation days do I get a year?

**Response:** I do not have information regarding what happens to unused PTO days beyond the 5 days that are allowed to roll over. I suggest you contact HR for more details.

**Why unhelpful:** The agent's final response states that it does not have the information and directs the user to HR, which is not useful.

**Low dimensions:** tool usage=1, specificity=0, scope compliance=0

### Q: How often can I work from home each week?

**Response:** Thank you for sharing that information. Since that detail is not included in the summary of company policies I have access to, I cannot confirm it. I recommend verifying this directly with HR or following the guidelines outlined in your onboarding packet.

**Why unhelpful:** The agent's final response does not answer the user's question about core hours, stating it does not have the information and directing the user to HR.

**Low dimensions:** specificity=0

### Q: How many sick days am I given annually?

**Response:** I do not have access to the full policy database or the onboarding packet. According to my guidelines, I can only provide answers based on the brief summary of company policy available to me, which does not contain information about doctor's note requirements. 

Please contact HR directly to verify this policy.

**Why unhelpful:** The agent failed to answer the user's follow-up question about the doctor's note policy, claiming it did not have access to the database and deflecting the user to HR.

**Low dimensions:** correctness=0, tool usage=1, specificity=0, scope compliance=0

### Q: How much will the company reimburse for tuition each year?

**Response:** I do not have information regarding how many paid holidays the company offers. I suggest you contact HR to get this information.

**Why unhelpful:** The agent failed to answer both the tuition reimbursement and paid holidays questions, which are in-scope topics, and instead deflected to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

