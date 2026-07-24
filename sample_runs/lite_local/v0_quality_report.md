# Quality Evaluation Report

Generated: 2026-07-22 22:35:52

## Summary

| Metric | Value |
|--------|-------|
| Total sessions | 13 |
| Meaningful | 8 (61.5%) |
| Unhelpful | 5 (38.5%) |
| &nbsp;&nbsp;↳ Skill gaps (evolution fixes) | 5 |
| &nbsp;&nbsp;↳ Knowledge gaps (add a fact) | 0 |
| &nbsp;&nbsp;↳ Tool gaps (build a tool) | 0 |
| **Addressable meaningful rate** (excl. knowledge + tool gaps) | **61.5%** |
| Partial | 0 |
| Declined (correct) | 0 |
| Correction rate | 0.0% |
| Avg corrections | 0.0 |
| Avg tool calls | 0.8 |
| Avg user turns | 2.5 |

## Quality Dimensions

| Dimension | Score (0-2) | Rating |
|-----------|-------------|--------|
| Correctness | 1.54 | Good |
| Tool Usage | 1.31 | Fair |
| Specificity | 1.23 | Fair |
| Scope Compliance | 1.69 | Good |
| First Time Right | 0.92 | Poor |

## Golden Eval Summary

| | Matched | Unmatched |
|---|---------|-----------|
| Total | 13 | 0 |
| Meaningful | 8 | 0 |
| Unhelpful | 5 | 0 |
| Partial | 0 | 0 |
| Meaningful rate | 61.5% | 0.0% |

### Failed Golden-Matched Questions (5)

**Q:** What percentage of my medical premium does the employer pay?
- Topic: benefits (similarity: 1.00)
- Expected: The company covers 80% of health insurance premiums for the employee (50% for dependents).
- Actual: I cannot answer that question. Please contact HR for information about medical premiums.

**Q:** What's the per-diem for meals while traveling for work?
- Topic: expenses (similarity: 1.00)
- Expected: $75 per day for meals during business travel.
- Actual: I do not have that information. Please contact HR for questions about travel per-diem.

**Q:** Can I do a compressed schedule of four 10-hour days?
- Topic: flex_time (similarity: 1.00)
- Expected: Yes - compressed work weeks like four 10-hour days are allowed with manager approval.
- Actual: The HR handbook doesn't contain specific information about compressed schedules of four 10-hour days. However, it does mention that flexible scheduling is available with manager approval, allowing employees to start between 7 am and 10 am, as long as they cover core hours and work a full 8-hour day.

**Q:** What portion of my pay does short-term disability replace?
- Topic: short_term_disability (similarity: 1.00)
- Expected: 60% of your salary.
- Actual: I do not have that information. Please contact HR.

**Q:** How much will the company reimburse for tuition each year?
- Topic: tuition_reimbursement (similarity: 1.00)
- Expected: Up to $5,250 per year for job-related courses.
- Actual: I am sorry, but I do not have access to the specific details of the tuition reimbursement policy. My knowledge is limited to the summary provided, which does not include that information. For details on tuition reimbursement, please contact HR.

## Category Breakdown

| Category | Count | % |
|----------|-------|---|
| Meaningful | 8 | 61.5% |
| Unhelpful | 5 | 38.5% |

## Unhelpful Sessions (5)

### Q: What percentage of my medical premium does the employer pay?

**Response:** I cannot answer that question. Please contact HR for information about medical premiums.

**Why unhelpful:** The agent stated it could not answer the question and directed the user to HR, which is not a useful substantive answer for an in-scope HR policy question.

**Low dimensions:** tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the per-diem for meals while traveling for work?

**Response:** I do not have that information. Please contact HR for questions about travel per-diem.

**Why unhelpful:** The agent stated it did not have the information and directed the user to HR, failing to provide the requested per-diem amount.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, first time right=0

### Q: Can I do a compressed schedule of four 10-hour days?

**Response:** The HR handbook doesn't contain specific information about compressed schedules of four 10-hour days. However, it does mention that flexible scheduling is available with manager approval, allowing employees to start between 7 am and 10 am, as long as they cover core hours and work a full 8-hour day. It also states that employees may work remotely up to 3 days per week with manager approval.

For a

**Why unhelpful:** The agent repeatedly failed to provide specific details about compressed schedules, instead offering generic information about flex time and remote work, and directing the user to their manager or HR.

**Low dimensions:** tool usage=1, specificity=0, first time right=0

### Q: What portion of my pay does short-term disability replace?

**Response:** I do not have that information. Please contact HR.

**Why unhelpful:** The agent initially stated it did not have the information and then encountered a tool error, failing to provide any useful answer.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, first time right=0

### Q: How much will the company reimburse for tuition each year?

**Response:** I am sorry, but I do not have access to the specific details of the tuition reimbursement policy. My knowledge is limited to the summary provided, which does not include that information. For details on tuition reimbursement, please contact HR.

**Why unhelpful:** The agent repeatedly stated it did not have the information and directed the user to HR, failing to use its policy_agent tool to look up the tuition reimbursement policy.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

