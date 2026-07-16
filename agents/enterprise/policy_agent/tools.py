# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tools for the Company Policy agent.

lookup_company_policy covers PTO, sick leave, remote work, expenses,
benefits (health/dental/vision/HSA/orthodontia/401k/parental leave),
holidays, bereavement leave, jury duty, the employee assistance program
(EAP), flex time, tuition reimbursement, and short-term disability.
get_current_date returns today's date.
"""

import datetime
import re
from zoneinfo import ZoneInfo

# Common synonyms callers use, mapped to canonical COMPANY_POLICIES keys.
_TOPIC_ALIASES = {
    "vacation": "pto",
    "annual_leave": "pto",
    "telecommuting": "remote_work",
    "work_from_home": "remote_work",
    "wfh": "remote_work",
    "reimbursement": "expenses",
    "health_insurance": "benefits",
    "insurance": "benefits",
    "medical": "benefits",
    "dental": "benefits",
    "vision": "benefits",
    "hsa": "benefits",
    "orthodontia": "benefits",
    "401k": "benefits",
    "retirement": "benefits",
    "pension": "benefits",
    "parental_leave": "benefits",
    "maternity_leave": "benefits",
    "paternity_leave": "benefits",
    "adoption_leave": "benefits",
    "enrollment": "benefits",
    "open_enrollment": "benefits",
    "employee_assistance_program": "eap",
    "counseling": "eap",
    "jury": "jury_duty",
    "flextime": "flex_time",
    "flexible_schedule": "flex_time",
    "tuition": "tuition_reimbursement",
    "education": "tuition_reimbursement",
    "disability": "short_term_disability",
    "std": "short_term_disability",
}

COMPANY_POLICIES = {
    "pto": {
        "days_per_year": 20,
        "accrual": "monthly",
        "rollover_max": 5,
        "separation_payout": "Unused accrued PTO is paid out at the final rate of pay",
        "details": (
            "Employees receive 20 days of PTO per year, accrued at approximately "
            "1.67 days per month. Unused PTO rolls over to the next year up to a "
            "maximum of 5 days. PTO requests must be submitted at least 2 weeks in "
            "advance for periods longer than 3 days. If you leave the company "
            "(resignation or termination) mid-year, any unused accrued PTO is paid "
            "out in your final paycheck at your current rate of pay."
        ),
    },
    "sick_leave": {
        "days_per_year": 10,
        "rollover": False,
        "details": (
            "Employees receive 10 sick days per year. Sick leave does not roll over. "
            "A doctor's note is required for absences longer than 3 consecutive days."
        ),
    },
    "remote_work": {
        "max_days_per_week": 3,
        "requires_approval": True,
        "details": (
            "Employees may work remotely up to 3 days per week with manager approval. "
            "Core collaboration hours are 10am-3pm in the employee's local timezone. "
            "Remote work arrangements must be documented in the HR system."
        ),
    },
    "expenses": {
        "meal_limit_daily": 75,
        "travel_approval_threshold": 500,
        "receipt_required_above": 25,
        "details": (
            "Business expenses must be submitted within 30 days. Meals are reimbursed "
            "up to $75/day during business travel. Travel expenses over $500 require "
            "pre-approval from your manager. Receipts are required for any expense "
            "over $25. Use the company expense portal at expenses.company.com."
        ),
    },
    "benefits": {
        "health_insurance": "PPO and HMO options, company covers 80% of premiums",
        "max_out_of_pocket": "$4,000 individual / $8,000 family (PPO, in-network)",
        "hsa": "Company contributes $750/year individual, $1,500/year family (HDHP)",
        "dental": "Full coverage for preventive care, 80% for major procedures",
        "orthodontia": "50% coverage up to a $2,000 lifetime maximum",
        "vision": "Annual eye exam covered, $200 frame allowance every 2 years",
        "retirement": "401(k) with 4% company match, vested after 1 year",
        "parental_leave": "16 weeks paid for primary caregiver, 8 weeks for secondary",
        "enrollment": (
            "Open enrollment runs every November; new hires must enroll within 30 "
            "days of their start date at benefits.company.com."
        ),
        "details": (
            "Health insurance: PPO and HMO plans available, company covers 80% of "
            "premiums for employee and 50% for dependents. Maximum out-of-pocket is "
            "$4,000 for an individual and $8,000 for a family (in-network, PPO). "
            "HSA: available with the HDHP plan; the company contributes $750/year "
            "for individual coverage and $1,500/year for family coverage. Dental: "
            "preventive care fully covered, 80% coverage for major procedures; "
            "orthodontia is covered at 50% up to a $2,000 lifetime maximum. Vision: "
            "annual eye exam covered, $200 frame allowance every 2 years. 401(k): 4% "
            "company match, fully vested after 1 year of employment. Parental leave: "
            "16 weeks paid for primary caregiver, 8 weeks for secondary caregiver "
            "(same for birth, adoption, or foster placement, including international "
            "adoption); leave may be taken in non-consecutive blocks within 12 "
            "months of birth/placement with manager coordination. To file, submit "
            "the parental leave request form plus proof of birth/placement to HR at "
            "least 30 days before the leave start date. Enrollment: open enrollment "
            "runs every November; new hires enroll within 30 days at "
            "benefits.company.com."
        ),
    },
    "holidays": {
        "2025": [
            "2025-01-01", "2025-01-20", "2025-02-17", "2025-05-26",
            "2025-07-04", "2025-09-01", "2025-11-27", "2025-11-28",
            "2025-12-24", "2025-12-25", "2025-12-31",
        ],
        "2026": [
            "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25",
            "2026-07-03", "2026-09-07", "2026-11-26", "2026-11-27",
            "2026-12-24", "2026-12-25", "2026-12-31",
        ],
        "details": (
            "The company observes 11 paid holidays per year: New Year's Day, "
            "Martin Luther King Jr. Day, Presidents' Day, Memorial Day, "
            "Independence Day, Labor Day, the Wednesday and Thursday of "
            "Thanksgiving week, Christmas Eve (Dec 24), Christmas Day (Dec 25), "
            "and New Year's Eve (Dec 31). Juneteenth, Veterans Day, and Columbus "
            "Day are NOT company holidays."
        ),
    },
    "bereavement": {
        "immediate_family_days": 5,
        "extended_family_days": 3,
        "details": (
            "Bereavement leave is 5 paid days for the loss of an immediate family "
            "member (spouse or domestic partner, child, parent, or sibling) and 3 "
            "paid days for an extended family member (grandparent, grandchild, or "
            "in-law). Additional unpaid time may be arranged with your manager. "
            "Notify your manager and HR; documentation is not required."
        ),
    },
    "jury_duty": {
        "paid": True,
        "cap_days": None,
        "details": (
            "Jury duty is fully paid for the entire duration of service with no day "
            "cap. Forward your jury summons to HR, and any jury stipend you receive "
            "may be kept. Bring your proof of service when you return."
        ),
    },
    "eap": {
        "sessions_per_year": 8,
        "details": (
            "Yes, the company offers an Employee Assistance Program (EAP): free, "
            "confidential counseling with up to 8 sessions per issue per year, plus "
            "a 24/7 hotline. It covers mental health, stress, legal, and financial "
            "matters for employees and household members. Reach it at "
            "eap.company.com or 1-800-555-0123."
        ),
    },
    "flex_time": {
        "requires_approval": True,
        "details": (
            "Flexible scheduling is available with manager approval: you may start "
            "any time between 7am and 10am as long as you cover the 10am-3pm core "
            "hours and work a full 8-hour day. Compressed-week arrangements (e.g. "
            "four 10-hour days) are also possible with manager approval."
        ),
    },
    "tuition_reimbursement": {
        "annual_max": 5250,
        "details": (
            "Tuition reimbursement covers up to $5,250 per calendar year for "
            "job-related courses or degree programs. Courses require manager "
            "pre-approval, and you must earn a grade of B or better (or pass for "
            "pass/fail courses) to be reimbursed."
        ),
    },
    "short_term_disability": {
        "income_replacement": "60% of salary",
        "max_weeks": 12,
        "details": (
            "Short-term disability covers 60% of your salary for up to 12 weeks "
            "after a 7-day waiting period, for a qualifying medical condition such "
            "as surgery or recovery. Coordinate with HR; sick leave can cover the "
            "waiting period. A physician's certification is required."
        ),
    },
}

# Topic ownership is split across two specialist agents so the supervisor must
# route correctly. Each lookup tool is domain-restricted: asking the wrong tool
# returns a routing hint rather than the answer.
POLICY_TOPICS = {
    "pto",
    "sick_leave",
    "remote_work",
    "expenses",
    "holidays",
    "bereavement",
    "jury_duty",
    "flex_time",
}
BENEFITS_TOPICS = {
    "benefits",
    "eap",
    "tuition_reimbursement",
    "short_term_disability",
}


def _resolve_topic(topic: str):
    """Resolve a free-text topic to a canonical (key, value) in COMPANY_POLICIES.

    Applies the synonym alias map, then exact match, then a fuzzy substring
    match. Returns (None, None) if nothing matches. No domain restriction --
    callers apply their own allow-list.
    """
    topic_key = topic.lower().replace(" ", "_").replace("-", "_")
    topic_key = _TOPIC_ALIASES.get(topic_key, topic_key)

    if topic_key in COMPANY_POLICIES:
        return topic_key, COMPANY_POLICIES[topic_key]
    for key, value in COMPANY_POLICIES.items():
        if topic_key in key or key in topic_key:
            return key, value
    return None, None


def _format_result(topic_key: str, result: dict) -> dict:
    """Resolve year-dependent fields (e.g. holidays default to current year)."""
    if topic_key == "holidays" or (isinstance(result, dict) and "2026" in result):
        now = datetime.datetime.now(tz=ZoneInfo("America/Los_Angeles"))
        current_year = str(now.year)
        if current_year in result:
            return {
                "year": current_year,
                "holidays": result[current_year],
                "details": result.get("details", ""),
            }
    return result


def lookup_company_policy(topic: str) -> dict:
    """Look up a TIME-OFF or WORKPLACE policy by topic.

    Args:
        topic: One of: pto, sick_leave, remote_work, expenses, holidays,
               bereavement, jury_duty, flex_time. Common synonyms (vacation,
               telecommuting, jury, flextime) are accepted. Benefits topics
               (insurance, 401k, parental leave, EAP, tuition, disability) are
               NOT handled here -- they belong to the benefits agent.

    Returns:
        A dict with policy details, or a routing hint if the topic is not a
        time-off/workplace policy.
    """
    topic_key, result = _resolve_topic(topic)
    if result is None or topic_key not in POLICY_TOPICS:
        return {
            "error": (
                f"'{topic}' is not a time-off/workplace policy handled here. "
                f"This tool covers: {', '.join(sorted(POLICY_TOPICS))}. "
                "Benefits topics (health/dental/vision insurance, HSA, 401k, "
                "parental leave, EAP, tuition reimbursement, short-term "
                "disability) are handled by the benefits agent."
            )
        }
    return _format_result(topic_key, result)


def lookup_benefits(topic: str) -> dict:
    """Look up an EMPLOYEE BENEFITS topic.

    Args:
        topic: A benefits topic -- health/dental/vision insurance, HSA,
               orthodontia, max out-of-pocket, 401k/retirement, parental and
               adoption leave, enrollment, EAP, tuition reimbursement, or
               short-term disability. Common synonyms are accepted. Time-off
               and workplace topics (PTO, sick leave, remote work, expenses,
               holidays, bereavement, jury duty, flex time) are NOT handled
               here -- they belong to the policy agent.

    Returns:
        A dict with benefits details, or a routing hint if the topic is not a
        benefits topic.
    """
    topic_key, result = _resolve_topic(topic)
    if result is None or topic_key not in BENEFITS_TOPICS:
        return {
            "error": (
                f"'{topic}' is not a benefits topic handled here. This tool "
                "covers: health/dental/vision insurance, HSA, orthodontia, max "
                "out-of-pocket, 401k/retirement, parental & adoption leave, "
                "enrollment, EAP, tuition reimbursement, short-term disability. "
                "Time-off/workplace topics (PTO, sick leave, remote work, "
                "expenses, holidays, bereavement, jury duty, flex time) are "
                "handled by the policy agent."
            )
        }
    return _format_result(topic_key, result)


def search_hr_handbook(query: str) -> dict:
    """Fuzzy keyword search across the entire HR handbook.

    Use this ONLY for open-ended questions when you do not know which specific
    topic applies. It returns the best-matching PARTIAL excerpts and is less
    precise than the exact lookup tools -- for a known topic, prefer
    lookup_company_policy or lookup_benefits to get the full, exact answer.

    Args:
        query: A free-text question or keywords.

    Returns:
        A dict with up to two partial handbook excerpts (topic + snippet).
    """
    words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 3}

    scored = []
    for key, value in COMPANY_POLICIES.items():
        text = value.get("details", "") if isinstance(value, dict) else str(value)
        overlap = sum(1 for w in words if w in text.lower())
        if overlap:
            scored.append((overlap, key, text))
    scored.sort(key=lambda x: -x[0])

    if not scored:
        return {
            "results": [],
            "note": (
                "No handbook passages matched. Try lookup_company_policy or "
                "lookup_benefits with a specific topic."
            ),
        }

    # Return only the first sentence of each match -- a partial excerpt. For
    # exact figures the caller should fall back to the lookup tools.
    results = []
    for _, key, text in scored[:2]:
        first = text.split(". ")[0].strip()
        if not first.endswith("."):
            first += "."
        results.append({"topic": key, "snippet": first})
    return {
        "results": results,
        "note": (
            "Partial handbook excerpts only. For exact figures use "
            "lookup_company_policy or lookup_benefits with the specific topic."
        ),
    }


def get_current_date() -> str:
    """Get the current date and day of the week.

    Returns:
        A string with today's date and day name.
    """
    now = datetime.datetime.now(tz=ZoneInfo("America/Los_Angeles"))
    return f"Today is {now.strftime('%A, %B %d, %Y')} (Pacific Time)"
