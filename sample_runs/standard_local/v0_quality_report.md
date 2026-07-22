# Quality Evaluation Report

Generated: 2026-07-22 06:47:58

## Summary

| Metric | Value |
|--------|-------|
| Total sessions | 25 |
| Meaningful | 14 (56.0%) |
| Unhelpful | 11 (44.0%) |
| &nbsp;&nbsp;↳ Skill gaps (evolution fixes) | 11 |
| &nbsp;&nbsp;↳ Knowledge gaps (add a fact) | 0 |
| &nbsp;&nbsp;↳ Tool gaps (build a tool) | 0 |
| **Addressable meaningful rate** (excl. knowledge + tool gaps) | **56.0%** |
| Partial | 0 |
| Declined (correct) | 0 |
| Correction rate | 0.0% |
| Avg corrections | 0.0 |
| Avg tool calls | 1.0 |
| Avg user turns | 2.3 |

## Quality Dimensions

| Dimension | Score (0-2) | Rating |
|-----------|-------------|--------|
| Correctness | 1.12 | Fair |
| Tool Usage | 1.12 | Fair |
| Specificity | 1.12 | Fair |
| Scope Compliance | 1.68 | Good |
| First Time Right | 1.04 | Fair |

## Golden Eval Summary

| | Matched | Unmatched |
|---|---------|-----------|
| Total | 25 | 0 |
| Meaningful | 14 | 0 |
| Unhelpful | 11 | 0 |
| Partial | 0 | 0 |
| Meaningful rate | 56.0% | 0.0% |

### Failed Golden-Matched Questions (11)

**Q:** What percentage of my medical premium does the employer pay?
- Topic: benefits (similarity: 1.00)
- Expected: The company covers 80% of health insurance premiums for the employee (50% for dependents).
- Actual: I cannot access external documents or specific policy documentation. My knowledge is limited to the summary provided. For details about employer contributions to medical premiums, please contact HR or use the benefits_agent.

**Q:** I make $104,000 a year. If I'm out 6 weeks on short-term disability, what's my total payout?
- Topic: calc (similarity: 1.00)
- Expected: $7,200 total ($1,200/week = 60% of weekly salary, for 6 weeks).
- Actual: I cannot calculate your total payout for short-term disability. The benefits agent shared that short-term disability provides 60% of your salary for up to 12 weeks. However, I do not have the functionality to calculate specific amounts. Please contact HR for further assistance.

**Q:** On a $130,000 salary, how much would short-term disability pay me per week?
- Topic: calc (similarity: 1.00)
- Expected: $1,500 per week (60% of the $2,500 weekly salary).
- Actual: I cannot calculate the exact amount. Short-term disability provides 60% of your salary. You may want to contact HR for further details.

**Q:** How many counseling visits does the EAP cover?
- Topic: eap (similarity: 1.00)
- Expected: Up to 8 counseling sessions per issue per year.
- Actual: 

**Q:** Is there a round-the-clock EAP support line?
- Topic: eap (similarity: 1.00)
- Expected: Yes - the EAP includes a 24/7 hotline.
- Actual: I am sorry, I cannot answer that question. Please contact HR for further assistance.

**Q:** What's the per-diem for meals while traveling for work?
- Topic: expenses (similarity: 1.00)
- Expected: $75 per day for meals during business travel.
- Actual: I do not have that information. Please contact HR.

**Q:** Is a receipt needed for a $40 purchase?
- Topic: expenses (similarity: 1.00)
- Expected: Yes - receipts are required for any expense over $25.
- Actual: I am sorry, I cannot directly access or check external documents like the official expense policy document. My knowledge is limited to the information provided in the company policy summary. For detailed information on receipt requirements, please contact the relevant department or HR.

**Q:** Can I do a compressed schedule of four 10-hour days?
- Topic: flex_time (similarity: 1.00)
- Expected: Yes - compressed work weeks like four 10-hour days are allowed with manager approval.
- Actual: I can only access the summary of the company policy provided to me. I do not have access to the full policy documents. For definitive answers regarding specific work arrangements like compressed schedules, please contact HR directly.

**Q:** How many company-paid holidays are there?
- Topic: holidays (similarity: 1.00)
- Expected: 11 paid holidays per year.
- Actual: I do not have that information. Please contact HR.

**Q:** What's the maximum duration of short-term disability?
- Topic: short_term_disability (similarity: 1.00)
- Expected: Short-term disability pays 60% of salary for up to 12 weeks.
- Actual: 

**Q:** What grade must I earn to get tuition reimbursed?
- Topic: tuition_reimbursement (similarity: 1.00)
- Expected: A grade of B or better is required for reimbursement.
- Actual: 

## Category Breakdown

| Category | Count | % |
|----------|-------|---|
| Meaningful | 14 | 56.0% |
| Unhelpful | 11 | 44.0% |

## Unhelpful Sessions (11)

### Q: What percentage of my medical premium does the employer pay?

**Response:** I cannot access external documents or specific policy documentation. My knowledge is limited to the summary provided. For details about employer contributions to medical premiums, please contact HR or use the benefits_agent.

**Why unhelpful:** The agent repeatedly stated it did not have the information and directed the user to HR or the benefits_agent, failing to provide any substantive answer.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: I make $104,000 a year. If I'm out 6 weeks on short-term disability, what's my total payout?

**Response:** I cannot calculate your total payout for short-term disability. The benefits agent shared that short-term disability provides 60% of your salary for up to 12 weeks. However, I do not have the functionality to calculate specific amounts. Please contact HR for further assistance.

**Why unhelpful:** The agent stated it could not calculate the payout and directed the user to HR, failing to use the hr_calculator tool which is designed for this purpose.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, first time right=0

### Q: On a $130,000 salary, how much would short-term disability pay me per week?

**Response:** I cannot calculate the exact amount. Short-term disability provides 60% of your salary. You may want to contact HR for further details.

**Why unhelpful:** The agent stated it could not calculate the exact amount and directed the user to HR, failing to use the available hr_calculator tool.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, first time right=0

### Q: How many counseling visits does the EAP cover?

**Response:** 

**Why unhelpful:** The agent responded with an error message indicating a tool was not found, failing to provide any information about the EAP coverage.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, first time right=0

### Q: Is there a round-the-clock EAP support line?

**Response:** I am sorry, I cannot answer that question. Please contact HR for further assistance.

**Why unhelpful:** The agent apologized and stated it could not answer the question, directing the user to HR instead of using its tools.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the per-diem for meals while traveling for work?

**Response:** I do not have that information. Please contact HR.

**Why unhelpful:** The agent repeatedly stated it did not have the information and directed the user to HR, failing to provide the requested policy information.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Is a receipt needed for a $40 purchase?

**Response:** I am sorry, I cannot directly access or check external documents like the official expense policy document. My knowledge is limited to the information provided in the company policy summary. For detailed information on receipt requirements, please contact the relevant department or HR.

**Why unhelpful:** The agent repeatedly stated it could not access the policy document and deflected the user to HR or the policy document itself, failing to provide the requested information.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, first time right=0

### Q: Can I do a compressed schedule of four 10-hour days?

**Response:** I can only access the summary of the company policy provided to me. I do not have access to the full policy documents. For definitive answers regarding specific work arrangements like compressed schedules, please contact HR directly.

**Why unhelpful:** The agent repeatedly stated it could not provide a definitive answer and deflected to HR, even after the user asked for a check of the policy document. The agent did not use its tools to find the answer.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, first time right=0

### Q: How many company-paid holidays are there?

**Response:** I do not have that information. Please contact HR.

**Why unhelpful:** The agent repeatedly stated it did not have the information and directed the user to HR, failing to provide the requested company policy information.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the maximum duration of short-term disability?

**Response:** 

**Why unhelpful:** The agent responded with an error message indicating a tool was not found, and did not provide any information about short-term disability.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, first time right=0

### Q: What grade must I earn to get tuition reimbursed?

**Response:** 

**Why unhelpful:** The agent returned an error message and a link to documentation instead of answering the user's question about tuition reimbursement.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, first time right=0

