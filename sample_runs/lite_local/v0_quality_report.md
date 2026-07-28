# Quality Evaluation Report

Generated: 2026-07-24 22:48:32

## Summary

| Metric | Value |
|--------|-------|
| Total sessions | 13 |
| Meaningful | 4 (30.8%) |
| Unhelpful | 8 (61.5%) |
| &nbsp;&nbsp;↳ Skill gaps (evolution fixes) | 9 |
| &nbsp;&nbsp;↳ Knowledge gaps (add a fact) | 0 |
| &nbsp;&nbsp;↳ Tool gaps (build a tool) | 0 |
| **Addressable meaningful rate** (excl. knowledge + tool gaps) | **30.8%** |
| Partial | 1 |
| Declined (correct) | 0 |
| Correction rate | 7.7% |
| Avg corrections | 0.1 |
| Avg tool calls | 0.6 |
| Avg user turns | 3.6 |

## Quality Dimensions

| Dimension | Score (0-2) | Rating |
|-----------|-------------|--------|
| Correctness | 1.08 | Fair |
| Tool Usage | 0.77 | Poor |
| Specificity | 0.92 | Poor |
| Scope Compliance | 0.31 | Poor |
| First Time Right | 0.77 | Poor |

## Golden Eval Summary

| | Matched | Unmatched |
|---|---------|-----------|
| Total | 13 | 0 |
| Meaningful | 4 | 0 |
| Unhelpful | 8 | 0 |
| Partial | 1 | 0 |
| Meaningful rate | 30.8% | 0.0% |

### Failed Golden-Matched Questions (8)

**Q:** How much bereavement leave do I get for losing a parent?
- Topic: bereavement (similarity: 1.00)
- Expected: 5 paid days (a parent is immediate family).
- Actual: I do not have access to information regarding bereavement leave in my summary of company policies. I suggest you contact HR directly to get the official policy details.

**Q:** What's the per-diem for meals while traveling for work?
- Topic: expenses (similarity: 1.00)
- Expected: $75 per day for meals during business travel.
- Actual: I do not have access to the official company policy database for travel expenses, and this information is not included in my policy summary. I recommend contacting HR directly to get the specific details regarding meal per-diems during business travel.

**Q:** How many company-paid holidays are there?
- Topic: holidays (similarity: 1.00)
- Expected: 11 paid holidays per year.
- Actual: I have checked my available resources again, but I do not have the information regarding the exact number of company-paid holidays in my summary. Because I do not have access to this information, I suggest you contact HR directly for the official details.

**Q:** Does the company pay me during jury duty, and is there a limit?
- Topic: jury_duty (similarity: 1.00)
- Expected: Jury duty is fully paid for the entire duration of service, with no day limit.
- Actual: I do not have information about paid holidays in my policy summary. I suggest you contact HR for details regarding the company's holiday schedule.

**Q:** How many vacation days do I get a year?
- Topic: pto (similarity: 1.00)
- Expected: 20 PTO days per year, accrued monthly.
- Actual: I do not have that information in my summary. I suggest you contact HR to find out if a doctor's note is required for multi-day sick leave.

**Q:** How often can I work from home each week?
- Topic: remote_work (similarity: 1.00)
- Expected: Up to 3 days per week with manager approval.
- Actual: Thank you for sharing that information! I will keep that in mind, though as a virtual assistant, my responses are limited to the specific summary provided to me. Please let me know if you have any other questions about PTO, sick leave, or general remote work days!

**Q:** How many sick days am I given annually?
- Topic: sick_leave (similarity: 1.00)
- Expected: 10 sick days per year; they do not roll over.
- Actual: I apologize for the limitation, but I only have access to a brief summary of the company policies, which does not contain details about doctor's note requirements. I do not have access to a broader policy database to double-check this for you. 

I suggest contacting HR directly, as they will be able

**Q:** How much will the company reimburse for tuition each year?
- Topic: tuition_reimbursement (similarity: 1.00)
- Expected: Up to $5,250 per year for job-related courses.
- Actual: I do not have information regarding paid holidays in my summary. I suggest you contact HR directly for details on the company's holiday schedule.

## Category Breakdown

| Category | Count | % |
|----------|-------|---|
| Meaningful | 4 | 30.8% |
| Partial | 1 | 7.7% |
| Unhelpful | 8 | 61.5% |

## Unhelpful Sessions (8)

### Q: How much bereavement leave do I get for losing a parent?

**Response:** I do not have access to information regarding bereavement leave in my summary of company policies. I suggest you contact HR directly to get the official policy details.

**Why unhelpful:** The agent deflected the question to HR and claimed it did not have access to the information, rather than using its policy_agent tool to look up the bereavement leave policy.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the per-diem for meals while traveling for work?

**Response:** I do not have access to the official company policy database for travel expenses, and this information is not included in my policy summary. I recommend contacting HR directly to get the specific details regarding meal per-diems during business travel.

**Why unhelpful:** The agent failed to answer the in-scope question about travel meal per-diem expenses and instead deflected the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How many company-paid holidays are there?

**Response:** I have checked my available resources again, but I do not have the information regarding the exact number of company-paid holidays in my summary. Because I do not have access to this information, I suggest you contact HR directly for the official details.

**Why unhelpful:** The agent failed to answer the user's question about company-paid holidays, which is an in-scope topic, and repeatedly deflected to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Does the company pay me during jury duty, and is there a limit?

**Response:** I do not have information about paid holidays in my policy summary. I suggest you contact HR for details regarding the company's holiday schedule.

**Why unhelpful:** The agent failed to answer both the jury duty and paid holidays questions, which are both in-scope. It repeatedly deflected to HR instead of using its tools to find the information.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How many vacation days do I get a year?

**Response:** I do not have that information in my summary. I suggest you contact HR to find out if a doctor's note is required for multi-day sick leave.

**Why unhelpful:** The agent deflected to HR and failed to answer the user's in-scope question about whether a doctor's note is required for multi-day sick leave.

**Low dimensions:** tool usage=1, specificity=0, scope compliance=0

### Q: How often can I work from home each week?

**Response:** Thank you for sharing that information! I will keep that in mind, though as a virtual assistant, my responses are limited to the specific summary provided to me. Please let me know if you have any other questions about PTO, sick leave, or general remote work days!

**Why unhelpful:** The conversation contains a user correction regarding core hours, and the agent merely acknowledged the correction without independently verifying it by re-querying its tools.

**Low dimensions:** tool usage=1, scope compliance=0

### Q: How many sick days am I given annually?

**Response:** I apologize for the limitation, but I only have access to a brief summary of the company policies, which does not contain details about doctor's note requirements. I do not have access to a broader policy database to double-check this for you. 

I suggest contacting HR directly, as they will be able to verify this requirement from the complete company policy database.

**Why unhelpful:** The agent failed to answer the user's follow-up question about the doctor's note requirement for sick leave, instead apologizing and deflecting the user to HR.

**Low dimensions:** correctness=1, tool usage=1, specificity=0, scope compliance=0

### Q: How much will the company reimburse for tuition each year?

**Response:** I do not have information regarding paid holidays in my summary. I suggest you contact HR directly for details on the company's holiday schedule.

**Why unhelpful:** The agent failed to answer both the tuition reimbursement and paid holidays questions, instead deflecting the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

## Partial Sessions (1)

- **Q:** How many counseling visits does the EAP cover?
  - The agent failed to answer the user's initial question about EAP counseling visits, but successfully answered the follow-up question about PTO rollover limits.

