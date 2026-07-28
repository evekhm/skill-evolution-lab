# Quality Evaluation Report

Generated: 2026-07-27 20:25:21

## Summary

| Metric | Value |
|--------|-------|
| Total sessions | 55 |
| Meaningful | 22 (40.0%) |
| Unhelpful | 33 (60.0%) |
| &nbsp;&nbsp;↳ Skill gaps (evolution fixes) | 29 |
| &nbsp;&nbsp;↳ Knowledge gaps (add a fact) | 4 |
| &nbsp;&nbsp;↳ Tool gaps (build a tool) | 0 |
| **Addressable meaningful rate** (excl. knowledge + tool gaps) | **43.1%** |
| Partial | 0 |
| Declined (correct) | 0 |
| Correction rate | 9.1% |
| Avg corrections | 0.1 |
| Avg tool calls | 0.9 |
| Avg user turns | 3.0 |

### Knowledge Gaps (add a fact to existing data)

In-scope questions the agent looked up correctly but its data source is silent on. Skill evolution cannot invent these facts — a human adds them to the knowledge base:

- How many sick days am I given annually?
- How often can I work from home each week?
- Does working remotely require sign-off from anyone?
- Do leftover sick days roll into the following year?

## Quality Dimensions

| Dimension | Score (0-2) | Rating |
|-----------|-------------|--------|
| Correctness | 1.05 | Fair |
| Tool Usage | 0.96 | Poor |
| Specificity | 0.93 | Poor |
| Scope Compliance | 0.87 | Poor |
| First Time Right | 0.93 | Poor |

## Golden Eval Summary

| | Matched | Unmatched |
|---|---------|-----------|
| Total | 55 | 0 |
| Meaningful | 22 | 0 |
| Unhelpful | 33 | 0 |
| Partial | 0 | 0 |
| Meaningful rate | 40.0% | 0.0% |

### Failed Golden-Matched Questions (33)

**Q:** How many unused vacation days carry into next year?
- Topic: pto (similarity: 1.00)
- Expected: Up to 5 unused PTO days roll over to the next year.
- Actual: I do not have information about what happens to any unused vacation days beyond the 5 days that roll over. I suggest you contact HR for clarification.

**Q:** Is my unused PTO paid out if I resign?
- Topic: pto (similarity: 1.00)
- Expected: Yes - unused accrued PTO is paid out at the final rate of pay on separation.
- Actual: I do not have access to the official company database or handbook, and that information is not in the summary of company policy available to me. I suggest you contact HR directly to get information regarding the policy on unused PTO payout upon resignation.

**Q:** How many sick days am I given annually?
- Topic: sick_leave (similarity: 1.00)
- Expected: 10 sick days per year; they do not roll over.
- Actual: I do not have access to the official company policy database or onboarding documents to double-check this. I am only able to provide information from the summary of company policy provided to me, which does not include details about doctor's notes. 

To ensure you have the correct and official infor

**Q:** Can I bank unused sick days for next year?
- Topic: sick_leave (similarity: 1.00)
- Expected: 10 sick days per year.
- Actual: I do not have access to the full policy database or onboarding documents. Because this topic is not covered in the summary of company policy I have, I do not have that information and suggest you contact HR directly to verify the doctor's note requirement.

**Q:** After how many days out sick is a doctor's note required?
- Topic: sick_leave (similarity: 1.00)
- Expected: Yes - a doctor's note is required for absences longer than 3 consecutive days.
- Actual: I do not have access to the official policy database or any information beyond the summary provided to me, which does not contain the rule regarding doctor's notes for consecutive sick days. 

I suggest contacting HR directly, as they will be able to check the official database and provide you with 

**Q:** How often can I work from home each week?
- Topic: remote_work (similarity: 1.00)
- Expected: Up to 3 days per week with manager approval.
- Actual: Thank you for sharing that. While your onboarding materials may contain those details, that information is not in the company policy summary available to me. For any official confirmation or further policy questions not covered in my summary, I recommend reaching out to HR.

**Q:** Does working remotely require sign-off from anyone?
- Topic: remote_work (similarity: 1.00)
- Expected: Yes - remote work requires manager approval (up to 3 days per week).
- Actual: Thank you for sharing that clarification! Since I only have access to a high-level summary of the company policies—which does not include details on core hours—I don't have that information in my records. Your onboarding packet is an excellent resource, and I recommend relying on it or contacting HR

**Q:** When are the required overlap hours for remote staff?
- Topic: remote_work (similarity: 1.00)
- Expected: Core collaboration hours are 10am-3pm in the employee's local timezone.
- Actual: I apologize, but I can only answer questions using the specific summary of company policy provided to me, which does not include information about core hours. For official confirmation of these hours, please contact HR.

**Q:** Am I allowed to be remote four days a week?
- Topic: remote_work (similarity: 1.00)
- Expected: The policy allows up to 3 remote days per week with manager approval; four is above the limit.
- Actual: I understand your question, but I am only authorized to answer questions using the specific summary of company policy provided to me, which does not contain information about core hours or recording remote work in the HR system. 

I suggest you contact HR directly, as they will be able to provide yo

**Q:** What's the per-diem for meals while traveling for work?
- Topic: expenses (similarity: 1.00)
- Expected: $75 per day for meals during business travel.
- Actual: According to the company policy summary, you get **20 PTO days per year**, which accrue monthly. Up to 5 unused PTO days can roll over to the next year.

**Q:** Does booking a $700 flight need approval first?
- Topic: expenses (similarity: 1.00)
- Expected: Yes - travel expenses over $500 require prior approval.
- Actual: I do not have information about flight bookings or expense approvals in my summary of company policy. I suggest you contact HR for assistance with this question.

**Q:** What percentage of my medical premium does the employer pay?
- Topic: benefits (similarity: 1.00)
- Expected: The company covers 80% of health insurance premiums for the employee (50% for dependents).
- Actual: I do not have access to the full onboarding documents or official policy files beyond the summary provided to me, which only states that the company offers competitive benefits. Since these specific medical premium coverage details are not in my summary, I do not have that information and suggest yo

**Q:** Which health plan types can I choose from?
- Topic: benefits (similarity: 1.00)
- Expected: PPO and HMO plans are available.
- Actual: I do not have access to any additional company policy documents beyond the summary provided to me, and it does not contain information regarding the number of paid holidays. I suggest you contact HR for this information.

**Q:** What's the individual in-network out-of-pocket cap?
- Topic: benefits (similarity: 1.00)
- Expected: $4,000 for an individual (in-network, PPO).
- Actual: I do not have access to the full policy documents to check that information. Please contact HR, as they will be able to assist you with the specific details regarding the individual in-network out-of-pocket cap.

**Q:** What's the employer HSA contribution for family coverage?
- Topic: benefits (similarity: 1.00)
- Expected: $1,500 per year for family coverage (HDHP).
- Actual: I do not have access to the full policy documents or onboarding packets in my summary. Because I do not have that information, I recommend contacting HR directly to get the accurate details regarding paid holidays.

**Q:** What does the company put in an HSA for a single employee?
- Topic: benefits (similarity: 1.00)
- Expected: $750 per year for individual coverage (HDHP).
- Actual: I do not have any information regarding paid holidays in the summary of company policy available to me. I suggest you contact HR to find out the official policy on paid holidays.

**Q:** Is a routine dental cleaning covered?
- Topic: benefits (similarity: 1.00)
- Expected: Yes - preventive dental care is fully covered.
- Actual: I do not have access to the detailed company benefits policy to check specific coverage details like routine dental cleanings. I recommend contacting HR directly, as they will be able to provide you with the complete benefits documentation and answer your questions.

**Q:** How much of a major dental procedure is covered?
- Topic: benefits (similarity: 1.00)
- Expected: 80% coverage for major dental procedures.
- Actual: I do not have access to the full company policy documents or specific dental coverage details in my summary. I recommend contacting HR directly to get the exact coverage information for major dental procedures.

**Q:** Are braces covered, and what's the cap?
- Topic: benefits (similarity: 1.00)
- Expected: Orthodontia is covered at 50% up to a $2,000 lifetime maximum.
- Actual: I do not have access to the full employee handbook or detailed benefits policy, so I do not have that information. I suggest you contact HR.

**Q:** How long until I'm fully vested in the match?
- Topic: benefits (similarity: 1.00)
- Expected: Fully vested after 1 year of employment.
- Actual: I do not have access to the employee handbook or policy documents to search for those details, as that information is not in my summary. I suggest you contact HR directly to get the specific details about our 401(k) vesting schedule.

**Q:** As a secondary caregiver, how much parental leave do I get?
- Topic: benefits (similarity: 1.00)
- Expected: 8 weeks for a secondary caregiver (16 weeks for primary).
- Actual: I do not have access to that information in the company policy summary provided to me. I suggest you contact HR directly for specific details regarding parental leave for secondary caregivers.

**Q:** How many company-paid holidays are there?
- Topic: holidays (similarity: 1.00)
- Expected: 11 paid holidays per year.
- Actual: I do not have access to search the full employee handbook or policy database. I only have access to a limited summary of company policies, which does not include information on company-paid holidays. Please contact HR directly for this information.

**Q:** Is the Wednesday before Thanksgiving a paid day off?
- Topic: holidays (similarity: 1.00)
- Expected: Thanksgiving week is covered by the 11-holiday calendar, including the Wednesday before Thanksgiving.
- Actual: I understand your surprise, but I am only authorized to answer questions using the specific summary provided to me, which does not contain the company's holiday calendar or the list of paid holidays. 

Please contact HR directly, as they will be able to check the official policy documents and verify

**Q:** How many days off if my sibling passes away?
- Topic: bereavement (similarity: 1.00)
- Expected: 5 paid days (a sibling is immediate family).
- Actual: I do not have that information in my company policy summary. I suggest you contact HR for assistance regarding bereavement leave.

**Q:** What's the bereavement allowance for a grandparent?
- Topic: bereavement (similarity: 1.00)
- Expected: 3 paid days (a grandparent is extended family).
- Actual: I do not have access to information beyond my provided summary, which does not include bereavement leave policies. I suggest you contact HR directly to check the official policy database for bereavement leave allowances.

**Q:** Is there a round-the-clock EAP support line?
- Topic: eap (similarity: 1.00)
- Expected: Yes - the EAP includes a 24/7 hotline.
- Actual: I do not have information about a round-the-clock Employee Assistance Program (EAP) support line in my summary. Please contact HR for assistance with this inquiry.

**Q:** How much will the company reimburse for tuition each year?
- Topic: tuition_reimbursement (similarity: 1.00)
- Expected: Up to $5,250 per year for job-related courses.
- Actual: I do not have information about tuition reimbursement in my summary. I suggest you contact HR for more information.

**Q:** What grade must I earn to get tuition reimbursed?
- Topic: tuition_reimbursement (similarity: 1.00)
- Expected: A grade of B or better is required for reimbursement.
- Actual: I do not have access to the official employee handbook or policy database to check for specific grade requirements for tuition reimbursement. Since this information is not in my summary, please contact HR for assistance with this question.

**Q:** What's the maximum duration of short-term disability?
- Topic: short_term_disability (similarity: 1.00)
- Expected: Short-term disability pays 60% of salary for up to 12 weeks.
- Actual: I do not have access to the full employee handbook or company policy database, and short-term disability is not included in the summary of company policies available to me. I do not have that information, so I suggest you contact HR for assistance.

**Q:** What fraction of dependent premiums does the employer cover?
- Topic: benefits (similarity: 1.00)
- Expected: 50% of premiums for dependents.
- Actual: Based on the company policy summary, you accrue 20 days of PTO per year, which are accrued monthly.

**Q:** Can I get reimbursed for a job-related class, and up to how much?
- Topic: tuition_reimbursement (similarity: 1.00)
- Expected: Yes - tuition reimbursement up to $5,250/year for job-related courses (manager pre-approval, grade B or better).
- Actual: I do not have that information in my summary of company policy. I suggest you contact HR to find out about reimbursement for job-related classes.

**Q:** Do leftover sick days roll into the following year?
- Topic: sick_leave (similarity: 1.00)
- Expected: Sick leave does not roll over.
- Actual: Thank you for sharing that. Since that detail is not included in the company policy summary I have access to, I cannot verify or confirm it. I recommend referring to your official onboarding documents or contacting HR directly to confirm their specific requirements.

**Q:** On a $130,000 salary, how much would short-term disability pay me per week?
- Topic: calc (similarity: 1.00)
- Expected: $1,500 per week (60% of the $2,500 weekly salary).
- Actual: I do not have access to the full employee handbook or benefits guide in my summary of company policy, and details about short-term disability coverage are not included. I suggest you contact HR directly to get the specific details from the employee handbook or benefits guide.

## Category Breakdown

| Category | Count | % |
|----------|-------|---|
| Meaningful | 22 | 40.0% |
| Unhelpful | 33 | 60.0% |

## Unhelpful Sessions (33)

### Q: How many unused vacation days carry into next year?

**Response:** I do not have information about what happens to any unused vacation days beyond the 5 days that roll over. I suggest you contact HR for clarification.

**Why unhelpful:** The agent's final response states that it does not have the information and directs the user to HR for an in-scope topic (PTO policy), which is unhelpful.

**Low dimensions:** tool usage=1, specificity=1, scope compliance=0

### Q: Is my unused PTO paid out if I resign?

**Response:** I do not have access to the official company database or handbook, and that information is not in the summary of company policy available to me. I suggest you contact HR directly to get information regarding the policy on unused PTO payout upon resignation.

**Why unhelpful:** The agent deflected the question by stating it did not have the information and directing the user to HR, which is unhelpful for an in-scope topic.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How many sick days am I given annually?

**Response:** I do not have access to the official company policy database or onboarding documents to double-check this. I am only able to provide information from the summary of company policy provided to me, which does not include details about doctor's notes. 

To ensure you have the correct and official information, I suggest you contact HR directly.

**Why unhelpful:** The agent was unable to answer the user's follow-up question about doctor's notes, stating it did not have the information and directing the user to HR.

**Low dimensions:** specificity=0

### Q: Can I bank unused sick days for next year?

**Response:** I do not have access to the full policy database or onboarding documents. Because this topic is not covered in the summary of company policy I have, I do not have that information and suggest you contact HR directly to verify the doctor's note requirement.

**Why unhelpful:** The agent's final response is unhelpful because it deflects to HR and claims it does not have access to the policy database, failing to answer an in-scope question about sick leave policy.

**Low dimensions:** tool usage=1, specificity=0, scope compliance=0

### Q: After how many days out sick is a doctor's note required?

**Response:** I do not have access to the official policy database or any information beyond the summary provided to me, which does not contain the rule regarding doctor's notes for consecutive sick days. 

I suggest contacting HR directly, as they will be able to check the official database and provide you with the exact policy.

**Why unhelpful:** The agent failed to answer an in-scope question about sick leave policy, claiming it did not have the information and directing the user to HR instead of using its tools.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How often can I work from home each week?

**Response:** Thank you for sharing that. While your onboarding materials may contain those details, that information is not in the company policy summary available to me. For any official confirmation or further policy questions not covered in my summary, I recommend reaching out to HR.

**Why unhelpful:** The agent's final response deflected to HR and stated it did not have the information about core hours, rather than providing a substantive answer.

**Low dimensions:** specificity=0

### Q: Does working remotely require sign-off from anyone?

**Response:** Thank you for sharing that clarification! Since I only have access to a high-level summary of the company policies—which does not include details on core hours—I don't have that information in my records. Your onboarding packet is an excellent resource, and I recommend relying on it or contacting HR directly for any further official details regarding your work schedule.

**Why unhelpful:** The agent failed to provide the core hours information, deflected to HR, and when corrected by the user, merely acknowledged the correction without independent verification.

### Q: When are the required overlap hours for remote staff?

**Response:** I apologize, but I can only answer questions using the specific summary of company policy provided to me, which does not include information about core hours. For official confirmation of these hours, please contact HR.

**Why unhelpful:** The agent failed to provide the requested information about remote work overlap hours, repeatedly stating it did not have the information and deflecting the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Am I allowed to be remote four days a week?

**Response:** I understand your question, but I am only authorized to answer questions using the specific summary of company policy provided to me, which does not contain information about core hours or recording remote work in the HR system. 

I suggest you contact HR directly, as they will be able to provide you with the official policy and specific details regarding these rules.

**Why unhelpful:** The agent's final response deflected the user's follow-up questions about remote work core hours and recording procedures to HR, failing to provide a substantive answer.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0

### Q: What's the per-diem for meals while traveling for work?

**Response:** According to the company policy summary, you get **20 PTO days per year**, which accrue monthly. Up to 5 unused PTO days can roll over to the next year.

**Why unhelpful:** The agent failed to answer the user's primary question about travel meal per-diem, claiming it did not have the information and deflecting to HR, which is an in-scope topic covered by the policy database.

**Low dimensions:** correctness=0, tool usage=1, scope compliance=0, first time right=0

### Q: Does booking a $700 flight need approval first?

**Response:** I do not have information about flight bookings or expense approvals in my summary of company policy. I suggest you contact HR for assistance with this question.

**Why unhelpful:** The agent deflected the question by stating it did not have the information and directing the user to HR, instead of using its tools to look up the company's expense policy.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What percentage of my medical premium does the employer pay?

**Response:** I do not have access to the full onboarding documents or official policy files beyond the summary provided to me, which only states that the company offers competitive benefits. Since these specific medical premium coverage details are not in my summary, I do not have that information and suggest you contact HR for assistance.

**Why unhelpful:** The agent failed to answer the question about medical premium coverage, claiming it did not have the information and deflecting the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Which health plan types can I choose from?

**Response:** I do not have access to any additional company policy documents beyond the summary provided to me, and it does not contain information regarding the number of paid holidays. I suggest you contact HR for this information.

**Why unhelpful:** The agent failed to answer both the health plan types and paid holidays questions, repeatedly deflecting to HR instead of using its tools.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the individual in-network out-of-pocket cap?

**Response:** I do not have access to the full policy documents to check that information. Please contact HR, as they will be able to assist you with the specific details regarding the individual in-network out-of-pocket cap.

**Why unhelpful:** The agent deflected the question to HR and claimed it did not have the information, rather than using its policy_agent tool to look up the answer.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the employer HSA contribution for family coverage?

**Response:** I do not have access to the full policy documents or onboarding packets in my summary. Because I do not have that information, I recommend contacting HR directly to get the accurate details regarding paid holidays.

**Why unhelpful:** The agent failed to answer both in-scope questions (employer HSA contribution and paid holidays) and instead deflected the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What does the company put in an HSA for a single employee?

**Response:** I do not have any information regarding paid holidays in the summary of company policy available to me. I suggest you contact HR to find out the official policy on paid holidays.

**Why unhelpful:** The agent failed to provide any useful information about HSA contributions or paid holidays, repeatedly deflecting the user to HR instead of using its tools.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Is a routine dental cleaning covered?

**Response:** I do not have access to the detailed company benefits policy to check specific coverage details like routine dental cleanings. I recommend contacting HR directly, as they will be able to provide you with the complete benefits documentation and answer your questions.

**Why unhelpful:** The agent deflected the question to HR and claimed it did not have access to the company benefits policy, failing to provide a substantive answer to an in-scope question.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How much of a major dental procedure is covered?

**Response:** I do not have access to the full company policy documents or specific dental coverage details in my summary. I recommend contacting HR directly to get the exact coverage information for major dental procedures.

**Why unhelpful:** The agent deflected the question by stating it did not have the information and directing the user to HR, instead of using its policy_agent tool to look up the dental coverage policy.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Are braces covered, and what's the cap?

**Response:** I do not have access to the full employee handbook or detailed benefits policy, so I do not have that information. I suggest you contact HR.

**Why unhelpful:** The agent deflected the question by stating it did not have the information and directing the user to HR, instead of using its tools to look up the company's dental policy.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How long until I'm fully vested in the match?

**Response:** I do not have access to the employee handbook or policy documents to search for those details, as that information is not in my summary. I suggest you contact HR directly to get the specific details about our 401(k) vesting schedule.

**Why unhelpful:** The agent deflected the user to HR instead of answering the in-scope question about 401(k) vesting.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: As a secondary caregiver, how much parental leave do I get?

**Response:** I do not have access to that information in the company policy summary provided to me. I suggest you contact HR directly for specific details regarding parental leave for secondary caregivers.

**Why unhelpful:** The agent deflected the question about parental leave (an in-scope topic) by claiming it did not have the information and directing the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How many company-paid holidays are there?

**Response:** I do not have access to search the full employee handbook or policy database. I only have access to a limited summary of company policies, which does not include information on company-paid holidays. Please contact HR directly for this information.

**Why unhelpful:** The agent repeatedly stated it did not have access to the information and directed the user to HR, failing to answer an in-scope question about company holidays.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Is the Wednesday before Thanksgiving a paid day off?

**Response:** I understand your surprise, but I am only authorized to answer questions using the specific summary provided to me, which does not contain the company's holiday calendar or the list of paid holidays. 

Please contact HR directly, as they will be able to check the official policy documents and verify the holiday schedule for you.

**Why unhelpful:** The agent failed to answer the user's question about the holiday policy, repeatedly stating that it did not have access to the information and deflecting the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How many days off if my sibling passes away?

**Response:** I do not have that information in my company policy summary. I suggest you contact HR for assistance regarding bereavement leave.

**Why unhelpful:** The agent deflected the user to HR instead of answering the in-scope question about bereavement leave.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the bereavement allowance for a grandparent?

**Response:** I do not have access to information beyond my provided summary, which does not include bereavement leave policies. I suggest you contact HR directly to check the official policy database for bereavement leave allowances.

**Why unhelpful:** The agent deflected the user to HR instead of using its tools to look up the bereavement policy, which is an in-scope topic.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Is there a round-the-clock EAP support line?

**Response:** I do not have information about a round-the-clock Employee Assistance Program (EAP) support line in my summary. Please contact HR for assistance with this inquiry.

**Why unhelpful:** The agent deflected the question by stating it did not have the information and directing the user to HR, instead of using its tools to find the answer.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: How much will the company reimburse for tuition each year?

**Response:** I do not have information about tuition reimbursement in my summary. I suggest you contact HR for more information.

**Why unhelpful:** The agent deflected the user to HR instead of using its tools to look up the tuition reimbursement policy, which is an in-scope topic.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What grade must I earn to get tuition reimbursed?

**Response:** I do not have access to the official employee handbook or policy database to check for specific grade requirements for tuition reimbursement. Since this information is not in my summary, please contact HR for assistance with this question.

**Why unhelpful:** The agent deflected the user to HR and claimed it did not have access to the policy database, failing to answer an in-scope question about tuition reimbursement.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What's the maximum duration of short-term disability?

**Response:** I do not have access to the full employee handbook or company policy database, and short-term disability is not included in the summary of company policies available to me. I do not have that information, so I suggest you contact HR for assistance.

**Why unhelpful:** The agent failed to answer the question about short-term disability, which is an in-scope topic, and instead deflected the user to HR.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: What fraction of dependent premiums does the employer cover?

**Response:** Based on the company policy summary, you accrue 20 days of PTO per year, which are accrued monthly.

**Why unhelpful:** The agent failed to answer the user's primary question about dependent premiums, claiming it did not have the information and deflecting to HR, even though this is an in-scope topic covered by its tools.

**Low dimensions:** tool usage=1, scope compliance=0, first time right=0

### Q: Can I get reimbursed for a job-related class, and up to how much?

**Response:** I do not have that information in my summary of company policy. I suggest you contact HR to find out about reimbursement for job-related classes.

**Why unhelpful:** The agent deflected the user to HR instead of answering the question about tuition reimbursement, which is an in-scope topic.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

### Q: Do leftover sick days roll into the following year?

**Response:** Thank you for sharing that. Since that detail is not included in the company policy summary I have access to, I cannot verify or confirm it. I recommend referring to your official onboarding documents or contacting HR directly to confirm their specific requirements.

**Why unhelpful:** The agent was unable to answer the user's question about the doctor's note policy, and when the user provided the correction, the agent merely acknowledged it without being able to verify it.

**Low dimensions:** specificity=0

### Q: On a $130,000 salary, how much would short-term disability pay me per week?

**Response:** I do not have access to the full employee handbook or benefits guide in my summary of company policy, and details about short-term disability coverage are not included. I suggest you contact HR directly to get the specific details from the employee handbook or benefits guide.

**Why unhelpful:** The agent deflected the question to HR and claimed it did not have the information, rather than using its available tools to answer the in-scope question.

**Low dimensions:** correctness=0, tool usage=0, specificity=0, scope compliance=0, first time right=0

