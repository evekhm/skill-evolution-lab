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

"""Verify agent responses to questions extracted from a Quality Agent issue file.

Parses questions from a markdown issue file, runs each through the local
supervisor agent, and judges responses using the LLM judge.

Usage:
    uv run python3 eval/verify_questions.py path/to/issue_file.md
    uv run python3 eval/verify_questions.py --questions-json questions.json
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

# Ensure project root is importable
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from eval.tests.test_eval import _build_local_supervisor, _run_agent  # noqa: E402
from eval.scoring.llm_judge import judge_response, load_scope_context  # noqa: E402


def extract_questions_from_issue(issue_path: str) -> list[str]:
    """Extract questions from a Quality Agent issue markdown file."""
    with open(issue_path) as f:
        content = f.read()

    questions = []
    # Match "- **Question:** ..." lines
    for m in re.finditer(r"- \*\*Question:\*\*\s*(.+)", content):
        questions.append(m.group(1).strip())
    # Also check quoted questions in reproduce sections
    for m in re.finditer(r'"(.+\?)"', content):
        q = m.group(1)
        if q not in questions and len(q) > 10:
            questions.append(q)

    return questions


async def verify(questions: list[str]) -> tuple[int, int, list[dict]]:
    """Run questions through the supervisor and judge responses.

    Returns (passed, failed, results).
    """
    supervisor = _build_local_supervisor()
    scope_context = load_scope_context()
    results = []

    for q in questions:
        agent_result = await _run_agent(supervisor, q)
        response = agent_result["response_text"]
        verdict = await judge_response(q, response, scope_context)
        passed = verdict["category"] in ("meaningful", "declined")
        results.append({
            "question": q,
            "response": response[:300],
            "passed": passed,
            "verdict": verdict,
        })

    num_passed = sum(1 for r in results if r["passed"])
    num_failed = sum(1 for r in results if not r["passed"])
    return num_passed, num_failed, results


def main():
    parser = argparse.ArgumentParser(
        description="Verify agent responses to questions from an issue file"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("issue_file", nargs="?", help="Path to issue markdown file")
    group.add_argument(
        "--questions-json", help="Path to JSON file with a list of question strings"
    )
    args = parser.parse_args()

    if args.questions_json:
        with open(args.questions_json) as f:
            questions = json.load(f)
    else:
        questions = extract_questions_from_issue(args.issue_file)

    if not questions:
        print("No questions found in issue file")
        sys.exit(0)

    print(f"Testing {len(questions)} questions from the issue:")
    for i, q in enumerate(questions, 1):
        print(f"  {i}. {q}")
    print()

    num_passed, num_failed, results = asyncio.run(verify(questions))

    print(f"Results: {num_passed}/{len(results)} passed, {num_failed} failed")
    print()
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['question']}")
        print(f"  Verdict: {r['verdict']['category']} -- {r['verdict']['reason']}")
        if not r["passed"]:
            print(f"  Response: {r['response']}")
        print()

    if num_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
