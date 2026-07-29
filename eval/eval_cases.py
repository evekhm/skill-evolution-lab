#!/usr/bin/env python3
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

"""Shared eval_cases utility module.

Provides read, write, and extraction functions for eval/data/eval_cases.json.
Used by the remediation_agent (reactive loop) and the skill_evolution agent.
"""

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_EVAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_EVAL_CASES_PATH = os.path.join(_EVAL_DIR, "eval_cases.json")

# Keyword → category mapping for inferring eval case categories
_CATEGORY_KEYWORDS = [
    (r"pto|vacation|paid time off|time off", "pto"),
    (r"sick\s*leave|illness|sick\s*day", "sick_leave"),
    (r"remote|wfh|work from home|telecommut", "remote_work"),
    (r"expense|reimburs|receipt", "expenses"),
    (r"holiday|company holiday", "holidays"),
    (r"dental|vision|health\s*insurance|medical|benefit", "benefits"),
    (r"retire|401k|pension|match", "retirement"),
    (r"parental|maternity|paternity|family leave", "parental_leave"),
    (r"education|tuition|training|professional dev", "education"),
    (r"salary|compensation|pay\s*raise|bonus", "compensation"),
]


def read_eval_cases() -> dict:
    """Read the golden eval cases from eval/data/eval_cases.json.

    Returns:
        The eval cases dict, or a dict with an 'error' key if not found.
    """
    if os.path.isfile(_EVAL_CASES_PATH):
        with open(_EVAL_CASES_PATH) as f:
            return json.load(f)
    return {"error": f"eval_cases.json not found at {_EVAL_CASES_PATH}"}


def add_eval_cases(cases: list[dict]) -> dict:
    """Append new eval cases, deduplicating by id.

    Reads the current eval_cases.json, skips any cases whose ``id``
    already exists, appends the rest, and writes back.

    Args:
        cases: List of case dicts, each with at least ``id`` and
            ``question`` fields.

    Returns:
        Dict with ``added``, ``skipped``, and ``total`` counts.
    """
    data = read_eval_cases()
    if "error" in data:
        # Bootstrap with empty structure
        data = {
            "eval_set_id": "knowledge_supervisor_quality",
            "name": "Knowledge Supervisor Golden Eval",
            "description": "Regression test cases.",
            "eval_cases": [],
        }

    existing_ids = {c["id"] for c in data["eval_cases"]}
    added = 0
    skipped = 0

    for case in cases:
        if case.get("id") in existing_ids:
            skipped += 1
            continue
        data["eval_cases"].append(case)
        existing_ids.add(case["id"])
        added += 1

    os.makedirs(os.path.dirname(_EVAL_CASES_PATH), exist_ok=True)
    with open(_EVAL_CASES_PATH, "w") as f:
        json.dump(data, f, indent=2)

    logger.info("Eval cases: added %d, skipped %d duplicates", added, skipped)
    return {"added": added, "skipped": skipped, "total": len(data["eval_cases"])}


def _infer_category(question: str) -> str:
    """Infer an eval case category from the question text."""
    q = question.lower()
    for pattern, category in _CATEGORY_KEYWORDS:
        if re.search(pattern, q):
            return category
    return "general"


def extract_regression_cases(quality_report: dict) -> list[dict]:
    """Extract failed sessions from a quality report as eval cases.

    Finds sessions with ``response_usefulness`` of ``unhelpful`` or
    ``partial`` and formats them as eval case entries.

    Args:
        quality_report: Dict with a ``sessions`` list (the output of
            ``generate_quality_report`` or ``_build_json_output``).

    Returns:
        List of eval case dicts ready for ``add_eval_cases``.
    """
    sessions = quality_report.get("sessions", [])
    cases = []

    for session in sessions:
        metrics = session.get("metrics", {})
        usefulness = metrics.get("response_usefulness", {})
        category_verdict = usefulness.get("category", "")

        if category_verdict not in ("unhelpful", "partial"):
            continue

        question = session.get("question", "")
        if not question:
            continue

        # Strip routing context noise (e.g. " | For context: ...")
        clean_q = question.split(" | For context:")[0].strip()

        session_id = session.get("session_id", "unknown")
        # Use a short hash of the session_id for the eval case id
        short_id = session_id[:12] if len(session_id) > 12 else session_id
        case_id = f"regression_{short_id}"

        case = {
            "id": case_id,
            "question": clean_q,
            "category": _infer_category(clean_q),
            "source": "skill_evolution",
            "source_session_id": session_id,
            "verdict": category_verdict,
        }
        # Routing is asserted only when a real specialist actually answered.
        # These are FAILED sessions: their route is part of the failure, and
        # 'knowledge_supervisor'/'unknown'/a default guess as expected_agent
        # turns the CI gate into a test the winner cannot legitimately pass
        # (a tool-first supervisor may answer directly and be correct).
        answered_by = (session.get("answered_by") or "").strip()
        if answered_by in ("policy_agent", "benefits_agent", "hr_calculator"):
            case["expected_agent"] = answered_by

        justification = usefulness.get("justification", "")
        if justification:
            case["failure_reason"] = justification

        cases.append(case)

    logger.info(
        "Extracted %d regression cases from %d sessions",
        len(cases),
        len(sessions),
    )
    return cases
