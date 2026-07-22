# Quality Evaluation Report

Generated: 2026-07-22 16:00:49

## Summary

| Metric | Value |
|--------|-------|
| Total sessions | 25 |
| Meaningful | 13 (52.0%) |
| Unhelpful | 9 (36.0%) |
| &nbsp;&nbsp;↳ Skill gaps (evolution fixes) | 9 |
| &nbsp;&nbsp;↳ Knowledge gaps (add a fact) | 0 |
| &nbsp;&nbsp;↳ Tool gaps (build a tool) | 0 |
| **Addressable meaningful rate** (excl. knowledge + tool gaps) | **52.0%** |
| Partial | 0 |
| Declined (correct) | 0 |
| Correction rate | 0.0% |
| Avg corrections | 0.0 |
| Avg tool calls | 0.9 |
| Avg user turns | 2.4 |

## Quality Dimensions

| Dimension | Score (0-2) | Rating |
|-----------|-------------|--------|
| Correctness | 1.18 | Fair |
| Tool Usage | 1.27 | Fair |
| Specificity | 1.36 | Fair |
| Scope Compliance | 1.45 | Fair |
| First Time Right | 1.18 | Fair |

## Golden Eval Summary

| | Matched | Unmatched |
|---|---------|-----------|
| Total | 25 | 0 |
| Meaningful | 13 | 0 |
| Unhelpful | 9 | 0 |
| Partial | 3 | 0 |
| Meaningful rate | 52.0% | 0.0% |

### Failed Golden-Matched Questions (9)

**Q:** What percentage of my medical premium does the employer pay?
- Topic: benefits (similarity: 1.00)
- Expected: The company covers 80% of health insurance premiums for the employee (50% for dependents).
- Actual: I do not have information on the specifics of medical premiums. Please contact HR or the benefits team for this information.

**Q:** Which health plan types can I choose from?
- Topic: benefits (similarity: 1.00)
- Expected: PPO and HMO plans are available.
- Actual: I do not have that information. Please contact HR for questions about health insurance.

**Q:** I make $104,000 a year. If I'm out 6 weeks on short-term disability, what's my total payout?
- Topic: calc (similarity: 1.00)
- Expected: $7,200 total ($1,200/week = 60% of weekly salary, for 6 weeks).
- Actual: You are correct. My apologies, I do not have that information. Please contact HR.

**Q:** How many counseling visits does the EAP cover?
- Topic: eap (similarity: 1.00)
- Expected: Up to 8 counseling sessions per issue per year.
- Actual: I cannot answer this question. The summary does not contain information about the EAP coverage. Please contact HR for this information.

**Q:** What's the per-diem for meals while traveling for work?
- Topic: expenses (similarity: 1.00)
- Expected: $75 per day for meals during business travel.
- Actual: I do not have that information. Please contact HR for questions about per-diem for meals.

**Q:** Is a receipt needed for a $40 purchase?
- Topic: expenses (similarity: 1.00)
- Expected: Yes - receipts are required for any expense over $25.
- Actual: No, a receipt is not needed for a $40 purchase.

**Q:** How many company-paid holidays are there?
- Topic: holidays (similarity: 1.00)
- Expected: 11 paid holidays per year.
- Actual: I do not have information on company-paid holidays. Please contact HR for this information.

**Q:** What portion of my pay does short-term disability replace?
- Topic: short_term_disability (similarity: 1.00)
- Expected: 60% of your salary.
- Actual: I cannot answer that question. Please contact HR for information about short-term disability.

**Q:** What's the maximum duration of short-term disability?
- Topic: short_term_disability (similarity: 1.00)
- Expected: Short-term disability pays 60% of salary for up to 12 weeks.
- Actual: The summary does not contain information about the maximum duration of short-term disability. Please contact HR for this information.

## Category Breakdown

| Category | Count | % |
|----------|-------|---|
| Meaningful | 13 | 52.0% |
| Unhelpful | 9 | 36.0% |

## Unhelpful Sessions (9)

### Q: What percentage of my medical premium does the employer pay?

**Response:** I do not have information on the specifics of medical premiums. Please contact HR or the benefits team for this information.

**Why unhelpful:** The agent stated it did not have the information and directed the user to HR, failing to provide a substantive answer to an in-scope question.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Which health plan types can I choose from?

**Response:** I do not have that information. Please contact HR for questions about health insurance.

**Why unhelpful:** The agent repeatedly states it does not have the information and deflects to HR, even after being prompted to check policy documentation. It also incorrectly states that 'health plan types' is not a supported benefit.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: I make $104,000 a year. If I'm out 6 weeks on short-term disability, what's my total payout?

**Response:** You are correct. My apologies, I do not have that information. Please contact HR.

**Why unhelpful:** The agent initially provided a calculation but then retracted it and stated it could not help, directing the user to HR.

**Low dimensions:** correctness=0, tool usage=1, scope compliance=0, first time right=0

### Q: How many counseling visits does the EAP cover?

**Response:** I cannot answer this question. The summary does not contain information about the EAP coverage. Please contact HR for this information.

**Why unhelpful:** The agent stated it could not answer the question and directed the user to HR, despite EAP being within the agent's scope and the policy_agent tool being available for such queries.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the per-diem for meals while traveling for work?

**Response:** I do not have that information. Please contact HR for questions about per-diem for meals.

**Why unhelpful:** The agent stated it did not have the information and directed the user to HR, failing to provide the per-diem amount.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, first time right=0

### Q: Is a receipt needed for a $40 purchase?

**Response:** No, a receipt is not needed for a $40 purchase.

**Why unhelpful:** The agent incorrectly stated that a receipt is not needed for a $40 purchase, when the policy requires one for purchases over $25.

**Low dimensions:** correctness=0, tool usage=1, first time right=0

### Q: How many company-paid holidays are there?

**Response:** I do not have information on company-paid holidays. Please contact HR for this information.

**Why unhelpful:** The agent repeatedly stated it did not have information and directed the user to HR, failing to answer the question even after the user provided context and asked for verification against policy.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What portion of my pay does short-term disability replace?

**Response:** I cannot answer that question. Please contact HR for information about short-term disability.

**Why unhelpful:** The agent repeatedly stated it could not answer the question and directed the user to HR, even after being asked to check the policy. This is unhelpful as it fails to provide any information.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the maximum duration of short-term disability?

**Response:** The summary does not contain information about the maximum duration of short-term disability. Please contact HR for this information.

**Why unhelpful:** The agent stated it did not have the information and directed the user to HR, failing to use its tools to find the answer.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, first time right=0

