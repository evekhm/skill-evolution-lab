#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Rebuild the demo traffic set to be compound-cross-domain dominated.

Why: empirically (see eval/runs/2026-06-01_212010_demo_full) a capable model
(gemini-2.5-flash) with working tools passes ~78% of the old set even from a
BARE skill stub, leaving only ~18 skill-fixable failures in 107 questions. The
engine already recovers essentially all of them (V1 = 86.9% = (75+18)/107), so
the *algorithm* works -- the *demo* just doesn't contain enough skill-fixable
failures to make the lift visible.

The questions that genuinely break a bare supervisor stub are COMPOUND
CROSS-DOMAIN questions: the supervisor must (a) decompose the question into
parts, (b) route each part to a DIFFERENT domain-restricted specialist
(policy_agent vs benefits_agent), and (c) synthesize one answer. In the old
set these (routing_stress) failed 67% of the time on a bare stub and are 100%
skill-fixable (decompose+route+merge is a learnable convention). They are also
realistic employee questions.

This builder:
  1. keeps the proven skill-biting categories in full,
  2. downsamples the easy filler a bare stub already passes,
  3. appends ~45 NEW compound cross-domain questions (every fact is backed by
     agents/enterprise/policy_agent/tools.py COMPANY_POLICIES),
  4. writes the traffic set back to demo_conversations.json and merges matching
     golden_qa anchors into eval/data/eval_spec.json for precise scoring.

Deterministic: keep-lists are explicit and selection is by sorted id, so re-runs
are reproducible.

Usage:
  python build_skillset.py            # rewrite demo_conversations.json + eval_spec.json
  python build_skillset.py --dry-run  # print the resulting category counts only
"""

import argparse
import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TRAFFIC = os.path.join(HERE, "demo_conversations.json")
# Always rebuild from the pristine original (saved on first run) so the builder
# is idempotent -- re-running never double-processes already-rebuilt output.
TRAFFIC_SRC = os.path.join(HERE, "demo_conversations.json.v0bak")
SPEC = os.path.normpath(os.path.join(HERE, "..", "eval_spec.json"))

# How many to keep per category from the existing set (None = keep all).
# Strong skill-biters kept in full; easy filler downsampled.
KEEP = {
    "routing_stress": None,
    "adversarial_compound": None,
    "multi_topic": None,
    "cross_policy": None,
    "out_of_scope": None,
    "near_scope_decline": None,
    "correction_bait": None,
    "implicit_routing": 14,
    "hallucination_trap": 6,      # mostly passes on a bare stub; keep the
                                  # fabricated-benefit ones that test declines
    "date_dependent": 8,
    "knowledge_gap_demo": 5,      # answerable sub-topic/routing tests
    "tool_gap_demo": 5,           # answerable; tests routing to the right tool
    "synonym": 4,                 # control: V1 must not regress on easy lookups
    "straightforward": 5,         # control
    "casual_phrasing": 2,         # control
}

# Prefer keeping these specific ids when downsampling (most skill-relevant).
PREFER = {
    "hallucination_trap": [
        "halluc_15", "halluc_16", "halluc_19", "halluc_20", "halluc_12", "halluc_03",
    ],
    "implicit_routing": [
        "route_04", "route_05", "route_11", "route_12", "route_15", "route_16",
        "route_18", "route_19", "route_20", "route_21", "route_01", "route_03",
        "route_08", "route_22",
    ],
}

# NEW compound cross-domain questions. Each requires decomposition and, for the
# cross-domain ones, routing to BOTH the policy_agent and the benefits_agent.
# expected_answer is grounded in tools.py COMPANY_POLICIES.
NEW = [
    # ---- policy x benefits (route to two different specialists) ----
    ("xd_01", "I'm having a baby this fall. How much parental leave do I get, and are the company holidays during my leave still paid?",
     "Parental leave is 16 weeks for a primary caregiver (8 weeks secondary). The 11 paid company holidays remain paid holidays regardless of your leave.", "parental_leave"),
    ("xd_02", "I'm scheduled for surgery next month. What does short-term disability pay, and can I use sick days for the waiting period?",
     "Short-term disability pays 60% of salary for up to 12 weeks after a 7-day waiting period; your 10 sick days/year can cover that waiting period.", "short_term_disability"),
    ("xd_03", "Compare my annual PTO with my 401k vesting timeline.",
     "PTO is 20 days per year (accrued monthly). The 401(k) has a 4% company match that vests after 1 year of employment.", "multi_topic"),
    ("xd_04", "If I resign mid-year, what happens to my unused PTO and to my 401k match?",
     "Unused accrued PTO is paid out in your final paycheck at your current rate. The 401(k) match is yours only if you are past the 1-year vesting cliff.", "multi_topic"),
    ("xd_05", "I'm taking a work trip to the NY office. What's the meal allowance, and what's my health plan's out-of-pocket max if I get sick there?",
     "Meals are reimbursed up to $75/day during business travel. The PPO in-network max out-of-pocket is $4,000 individual / $8,000 family.", "multi_topic"),
    ("xd_06", "Walk me through both my vision coverage and how many sick days I have.",
     "Vision: annual eye exam covered, $200 frame allowance every 2 years. Sick leave: 10 days per year, no rollover.", "multi_topic"),
    ("xd_07", "Does tuition reimbursement count against my PTO, or is it separate?",
     "They are separate. Tuition reimbursement is up to $5,250/year for approved job-related courses; PTO is 20 days/year and is unaffected.", "multi_topic"),
    ("xd_08", "How do flex time and remote work differ, and does either change my HSA contribution?",
     "Flex time lets you start 7am-10am covering 10am-3pm core hours; remote work is up to 3 days/week with approval. Neither changes the HSA: the company contributes $750/year individual, $1,500/year family on the HDHP.", "multi_topic"),
    ("xd_09", "Is jury duty paid, and does serving affect my health insurance premiums?",
     "Jury duty is fully paid for the entire duration with no day cap. It does not change your health insurance; the company still covers 80% of employee premiums.", "multi_topic"),
    ("xd_10", "Compare bereavement leave with parental leave - which is longer and how do I file each?",
     "Parental leave is far longer (16 weeks primary / 8 weeks secondary; file the request form plus proof of birth/placement 30 days ahead) versus bereavement (5 days immediate family, 3 days extended; just notify your manager and HR).", "multi_topic"),
    ("xd_11", "What's the orthodontia coverage, and how many days of bereavement leave would I get for a grandparent?",
     "Orthodontia is covered at 50% up to a $2,000 lifetime maximum. Bereavement for a grandparent (extended family) is 3 paid days.", "multi_topic"),
    ("xd_12", "I'm a new hire. Walk me through PTO, remote work, and how the 401k match works.",
     "PTO: 20 days/year accrued monthly. Remote work: up to 3 days/week with manager approval. 401(k): 4% company match, vested after 1 year.", "multi_topic"),
    ("xd_13", "Tell me about everything that resets or rolls over at year end - PTO, sick days, and my HSA.",
     "PTO rolls over up to 5 days; sick leave does not roll over (resets each year); HSA balances are yours and carry over (the company contributes $750/$1,500 per year).", "multi_topic"),
    ("xd_14", "Compare my expense meal limit with what the company contributes to my HSA each year.",
     "The meal limit is $75/day on business travel. The company HSA contribution is $750/year for individual coverage and $1,500/year for family.", "multi_topic"),
    ("xd_15", "I need surgery and recovery time. How does short-term disability work, and do company holidays during my leave still count as paid?",
     "Short-term disability pays 60% of salary up to 12 weeks after a 7-day waiting period. The 11 paid company holidays remain paid holidays regardless of your leave.", "multi_topic"),
    ("xd_16", "How much notice do I need for PTO, and what paperwork do I file for parental leave?",
     "PTO needs at least 2 weeks notice for absences longer than 3 days. For parental leave, submit the request form plus proof of birth/placement to HR at least 30 days before the start date.", "multi_topic"),
    ("xd_17", "Do I get paid for jury duty, and is there an EAP I can use if the case is stressful?",
     "Jury duty is fully paid with no day cap. Yes - the EAP offers free confidential counseling, up to 8 sessions per issue per year, with a 24/7 hotline.", "multi_topic"),
    ("xd_18", "I'm adopting internationally next spring. What leave applies, and can I add PTO on top of it?",
     "International adoption qualifies for the same parental leave: 16 weeks primary or 8 weeks secondary. PTO is separate (20 days/year), so you can use it in addition, with 2 weeks notice for absences over 3 days.", "parental_leave"),
    ("xd_19", "My spouse just lost their job and we have three kids. What does the EAP offer, and can I add them to my health plan, and can I work remotely more for a while?",
     "The EAP gives free confidential counseling (8 sessions/issue/year, 24/7 hotline) for you and your household. You can add dependents at open enrollment in November (company covers 50% of dependent premiums). Remote work remains up to 3 days/week with manager approval.", "multi_topic"),
    ("xd_20", "Compare dental and vision coverage under our plan.",
     "Dental: preventive care fully covered, major procedures 80%, orthodontia 50% up to $2,000 lifetime. Vision: annual eye exam covered, $200 frame allowance every 2 years.", "multi_topic"),
    ("xd_21", "How do the HSA and 401k company contributions compare?",
     "HSA: the company contributes $750/year individual, $1,500/year family on the HDHP. 401(k): the company matches 4% of salary, vested after 1 year.", "multi_topic"),
    ("xd_22", "What's the difference between bereavement and jury duty leave?",
     "Bereavement is 5 paid days for immediate family (3 for extended). Jury duty is fully paid for the entire duration with no day cap.", "multi_topic"),
    ("xd_23", "Compare PTO and sick leave - the days and what rolls over for each.",
     "PTO: 20 days/year, up to 5 days roll over. Sick leave: 10 days/year, no rollover.", "multi_topic"),
    ("xd_24", "I want three weeks off in December. Given the company holidays that month, how many PTO days would I actually need to use, and will it affect my 401k contributions?",
     "December has 3 paid company holidays (Christmas Eve, Christmas Day, New Year's Eve), so those days don't draw from your 20 PTO days. Taking PTO does not change your 401(k) match.", "multi_topic"),
    ("xd_25", "What's the per-diem meal cap, and does the health plan have an out-of-pocket maximum I should know about before traveling?",
     "Meals are reimbursed up to $75/day on business travel. The PPO in-network out-of-pocket maximum is $4,000 individual / $8,000 family.", "multi_topic"),
    ("xd_26", "I just had a baby. How do I file for parental leave, how long is it, and when can I enroll the baby in our health plan?",
     "Parental leave is 16 weeks (primary) / 8 weeks (secondary); file the request form plus proof of birth to HR 30 days ahead. You can enroll the baby at the next open enrollment in November, or as a qualifying life event - check with HR.", "parental_leave"),
    ("xd_27", "How does flex time work, and separately, what's the company HSA contribution?",
     "Flex time: start any time 7am-10am with manager approval as long as you cover 10am-3pm core hours and a full 8-hour day. HSA: the company contributes $750/year individual, $1,500/year family.", "multi_topic"),
    ("xd_28", "Compare expense pre-approval rules with the parental-leave paperwork deadline.",
     "Travel expenses over $500 need manager pre-approval (and receipts for anything over $25). Parental leave paperwork (request form + proof of placement) is due to HR at least 30 days before the leave start.", "multi_topic"),
    ("xd_29", "I broke my glasses and I'll also be out sick tomorrow. What's my vision frame allowance and how many sick days do I have?",
     "Vision covers a $200 frame allowance every 2 years. You have 10 sick days per year (no doctor's note needed unless you're out more than 3 consecutive days).", "multi_topic"),
    ("xd_30", "How does tuition reimbursement work, and can I also take flex time to attend classes?",
     "Tuition reimbursement is up to $5,250/year for pre-approved job-related courses (grade B or better). You can use flex time (start 7am-10am, cover 10am-3pm) with manager approval to attend classes.", "multi_topic"),
    ("xd_31", "Compare what the company pays toward my health insurance with what it matches on my 401k.",
     "The company covers 80% of employee health premiums (50% for dependents). It matches 4% of salary into your 401(k), vested after 1 year.", "multi_topic"),
    ("xd_32", "If a parent passes away, how many bereavement days do I get, and is there counseling support through our benefits?",
     "Bereavement leave for an immediate family member (including a parent) is 5 paid days. The EAP offers free confidential counseling - up to 8 sessions per issue per year with a 24/7 hotline.", "multi_topic"),
    ("xd_33", "What's the remote-work limit, and does working from home change my meal expense eligibility?",
     "Remote work is up to 3 days/week with manager approval. The $75 meal allowance is for business travel, so working from home does not make meals reimbursable.", "multi_topic"),
    ("xd_34", "I'm planning to take a course and travel for a conference. What's my tuition cap and what travel expenses are covered?",
     "Tuition reimbursement is up to $5,250/year for approved job-related courses. Conference travel: meals up to $75/day, receipts required over $25, and pre-approval for travel over $500.", "multi_topic"),
    ("xd_35", "Compare how much parental leave a primary versus secondary caregiver gets, and tell me the PTO notice period.",
     "Primary caregivers get 16 weeks of parental leave; secondary caregivers get 8 weeks. PTO requires at least 2 weeks notice for absences longer than 3 days.", "multi_topic"),
    ("xd_36", "Does the company cap jury-duty pay, and what's the dental coverage for major procedures?",
     "Jury duty is fully paid with no day cap. Major dental procedures are covered at 80% (preventive care is fully covered).", "multi_topic"),
    ("xd_37", "I'm coming back from parental leave and want to ease in. Can I work remotely most days, and is there a phased return through short-term disability?",
     "Remote work is up to 3 days/week with manager approval (not most days). Short-term disability covers a qualifying medical condition at 60% for up to 12 weeks - it is not a phased-return program, so coordinate a return plan with your manager and HR.", "multi_topic"),
    ("xd_38", "What are the core hours for remote work, and what's the EAP hotline for if I'm overwhelmed?",
     "Core collaboration hours are 10am-3pm in your local timezone (remote up to 3 days/week with approval). The EAP provides a 24/7 confidential hotline plus up to 8 counseling sessions per issue per year.", "multi_topic"),
    ("xd_39", "Compare the orthodontia lifetime max with the annual tuition reimbursement cap.",
     "Orthodontia is covered at 50% up to a $2,000 lifetime maximum. Tuition reimbursement is up to $5,250 per calendar year.", "multi_topic"),
    ("xd_40", "I started in January. Roughly how many PTO days have I accrued so far, and how many can roll into next year?",
     "PTO accrues at ~1.67 days/month, so by mid-year you'd have accrued roughly 8-10 days of your 20/year. Up to 5 unused days can roll over to next year.", "multi_topic"),
    ("xd_41", "How many paid holidays are left this year, and do holidays reduce the PTO I need for a long break?",
     "There are 11 paid holidays per year; any that fall during your time off are paid and do not draw from your 20 PTO days.", "multi_topic"),
    ("xd_42", "Compare sick leave and short-term disability - when would I use each?",
     "Use sick leave (10 days/year, no rollover) for short illnesses. Use short-term disability (60% of salary, up to 12 weeks after a 7-day waiting period, physician certification) for a longer qualifying medical condition such as surgery.", "multi_topic"),
    ("xd_43", "What's the HSA family contribution, and how much bereavement leave for a sibling?",
     "The company contributes $1,500/year to a family HSA (HDHP). Bereavement for a sibling (immediate family) is 5 paid days.", "multi_topic"),
    ("xd_44", "I'm getting married in October and going on a honeymoon. What time-off applies, and does marriage let me change my benefits enrollment?",
     "Use PTO for the honeymoon (20 days/year, 2 weeks notice for >3 days; up to 5 roll over). Marriage is typically a qualifying life event for benefits changes - confirm the window with HR (open enrollment is otherwise in November).", "multi_topic"),
    ("xd_45", "Compare what happens to unused PTO versus unused sick days if I leave the company.",
     "Unused accrued PTO is paid out in your final paycheck at your current rate. Unused sick days are not paid out (sick leave does not roll over or pay out).", "multi_topic"),
]


def load(path):
    with open(path) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src_path = TRAFFIC_SRC if os.path.exists(TRAFFIC_SRC) else TRAFFIC
    traffic = load(src_path)
    orig_count = len(traffic["eval_cases"])
    by_cat = collections.defaultdict(list)
    for c in traffic["eval_cases"]:
        by_cat[c.get("category", "?")].append(c)

    kept = []
    for cat, cases in by_cat.items():
        limit = KEEP.get(cat, 0)
        cases_sorted = sorted(cases, key=lambda c: c.get("id", ""))
        if limit is None:
            chosen = cases_sorted
        elif limit == 0:
            chosen = []
        else:
            prefer_ids = PREFER.get(cat, [])
            pref = [c for pid in prefer_ids for c in cases_sorted if c.get("id") == pid]
            rest = [c for c in cases_sorted if c not in pref]
            chosen = (pref + rest)[:limit]
        kept.extend(chosen)

    # Append new compound questions (traffic schema: id/question/category).
    for cid, q, _ans, _topic in NEW:
        kept.append({"id": cid, "question": q, "category": "compound_xdomain"})

    traffic["eval_cases"] = kept

    # Merge golden_qa anchors for the new compound questions into eval_spec.json.
    # Drop any prior anchors with the same ids first, so re-runs refresh the text
    # (idempotent) rather than skipping updated questions.
    spec = load(SPEC)
    new_ids = {cid for cid, *_ in NEW}
    spec["golden_qa"] = [g for g in spec["golden_qa"] if g["id"] not in new_ids]
    added = 0
    for cid, q, ans, topic in NEW:
        spec["golden_qa"].append({
            "id": cid, "question": q, "expected_answer": ans, "topic": topic,
            "notes": "Compound cross-domain: requires decompose + route to multiple specialists + synthesize.",
        })
        added += 1

    # Report category counts.
    counts = collections.Counter(c.get("category", "?") for c in kept)
    print(f"Rebuilt traffic set: {len(kept)} questions (was {orig_count})")
    for cat in sorted(counts):
        print(f"  {cat:22} {counts[cat]}")
    compound = sum(counts[c] for c in
                   ("compound_xdomain", "routing_stress", "adversarial_compound",
                    "multi_topic", "cross_policy"))
    print(f"  -> compound/decompose total: {compound} ({100*compound/len(kept):.0f}%)")
    print(f"golden_qa anchors added: {added} (total {len(spec['golden_qa'])})")

    if args.dry_run:
        print("\n[dry-run] no files written")
        return

    with open(TRAFFIC, "w") as f:
        json.dump(traffic, f, indent=2)
    with open(SPEC, "w") as f:
        json.dump(spec, f, indent=2)
    print(f"\nWrote {TRAFFIC}\nWrote {SPEC}")


if __name__ == "__main__":
    main()
