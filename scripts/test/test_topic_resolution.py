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

"""Tool-layer regression test for semantic topic resolution.

Every phrasing below previously bounced off the lookup tools and was
misdiagnosed as a knowledge gap. The facts all exist in COMPANY_POLICIES;
this test proves the LLM resolver actually reaches them, that domain
routing hints still fire for wrong-tool calls, and that the disability
calculator returns exact dollars.
"""

import sys

from agents.enterprise.hr_calculator.agent import calculate_disability_pay
from agents.enterprise.policy_agent.tools import (
    lookup_benefits,
    lookup_company_policy,
    search_hr_handbook,
)

FAILURES = []


def check(name: str, ok: bool, detail: str) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}: {detail[:110]}")
    if not ok:
        FAILURES.append(name)


def main() -> int:
    print("lookup_benefits — phrasings that previously returned errors:")
    r = lookup_benefits("HSA family coverage")
    check("hsa family", "1,500" in str(r), str(r))
    r = lookup_benefits("401k match")
    check("401k match", "4%" in str(r), str(r))
    r = lookup_benefits("401k match vesting after six months")
    check("vesting", "1 year" in str(r), str(r))
    r = lookup_benefits("preventive dental cleanings")
    check("dental preventive", "preventive" in str(r).lower(), str(r))
    r = lookup_benefits("annual tuition reimbursement limit")
    check("tuition limit", "5,250" in str(r), str(r))
    r = lookup_benefits("short-term disability payout")
    check("std policy", "60%" in str(r), str(r))

    print("lookup_company_policy — phrasings that previously returned errors:")
    r = lookup_company_policy("core collaboration hours for remote work")
    check("core hours", "10am-3pm" in str(r), str(r))
    r = lookup_company_policy("daily meal reimbursement limit on business travel")
    check("meal limit", "75" in str(r), str(r))

    print("Domain routing hints still fire for wrong-tool calls:")
    r = lookup_benefits("vacation days")
    check("benefits rejects pto", "error" in r, str(r))
    r = lookup_company_policy("401k")
    check("policy rejects 401k", "error" in r, str(r))

    print("search_hr_handbook — semantic, no keyword overlap needed:")
    r = search_hr_handbook("Do we get money for taking classes?")
    topics = [x["topic"] for x in r.get("results", [])]
    check("handbook tuition", "tuition_reimbursement" in topics, str(topics))

    print("calculate_disability_pay — exact dollars, no mental math:")
    r = calculate_disability_pay(annual_salary=117000, weeks_out=8)
    check("std $117k/8w", r["total_benefit"] == 10800.0, str(r))
    r = calculate_disability_pay(annual_salary=65000, weeks_out=14)
    check("std cap 12w", r["covered_weeks"] == 12 and r["weekly_benefit"] == 750.0, str(r))
    r = calculate_disability_pay(annual_salary=182000, weeks_out=1)
    check("std $182k/wk", r["weekly_benefit"] == 2100.0, str(r))

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
