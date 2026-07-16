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

"""Load test — generates fresh traffic and enforces operational baselines.

Generates synthetic questions via the traffic generator, runs them through
the supervisor agent locally, judges each response with an LLM, and asserts
operational baselines defined in eval/baselines.json:

    1. Quality gate   — meaningful response rate >= quality_threshold
    2. Error rate     — error_rate <= budget
    3. Latency budget — P95 latency <= p95_latency_ms
    4. All baselines  — every metric in baselines.json checked

Budgets are read from eval/baselines.json (single source of truth).
Environment variables override individual budgets for CI flexibility.

Run in CI on every PR (eval.yml) alongside golden eval tests.

Usage:
    uv run pytest eval/test_load.py -v
    LOAD_TEST_COUNT=20 uv run pytest eval/test_load.py -v

Environment (overrides for baselines.json values):
    LOAD_TEST_COUNT              Number of questions (default: 10)
    LOAD_TEST_THRESHOLD          Override quality_threshold from baselines.json
    LOAD_TEST_LATENCY_BUDGET_MS  Override p95_latency_ms from baselines.json
    EVAL_MODEL_ID                Model for the agent (default: gemini-2.5-flash)

Recalibrate baselines from observed metrics:
    python eval/check_budget.py eval/load_test_report.json --record-baseline

Output:
    eval/load_test_report.json — per-question results, LLM judge verdicts,
    latency, and summary metrics.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load .env and configure Vertex AI before any ADK imports
# ---------------------------------------------------------------------------

from dotenv import load_dotenv

_project_root = Path(__file__).parent.parent.parent
_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=str(_env_path))

import google.auth

_, _auth_project = google.auth.default()
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
os.environ.setdefault(
    "GOOGLE_CLOUD_PROJECT", os.getenv("PROJECT_ID", _auth_project or "")
)
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", os.getenv("REGION", "us-central1"))

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from agents.enterprise.knowledge_supervisor.app.prompts import SUPERVISOR_INSTRUCTION
from agents.enterprise.policy_agent.agent import create_agent as create_policy_agent
from agents.enterprise.hr_calculator.agent import (
    calculate_pto_details,
    calculate_working_days_for_period,
    get_remaining_working_days,
)
from agents.workflow.traffic_generator.main import (
    generate_all_questions,
    parse_topics_config,
)

# ---------------------------------------------------------------------------
# Configuration — baselines.json is the source of truth, env vars override
# ---------------------------------------------------------------------------

EVAL_DIR = Path(__file__).parent
BASELINES_PATH = EVAL_DIR.parent / "data" / "baselines.json"

def _load_baselines() -> dict:
    """Load budgets from baselines.json."""
    if BASELINES_PATH.exists():
        with open(BASELINES_PATH) as f:
            return json.load(f).get("budgets", {})
    return {}

_baselines = _load_baselines()

MODEL_ID = os.getenv("EVAL_MODEL_ID", "gemini-2.5-flash")
COUNT = int(os.getenv("LOAD_TEST_COUNT", "10"))

# The production-loop demo keeps a deliberately flawed V0 policy skill on main
# (baked facts + defer-to-HR); create_policy_agent() loads it, so fresh traffic
# scores well below the evolved-quality budgets until an evolution PR bumps the
# skill version. Quality assertions xfail non-strictly while the baseline is
# active and hard-assert on evolution PRs.
from agents.enterprise.policy_agent.skill_loader import skill_is_baseline

_BASELINE_POLICY = skill_is_baseline(
    str(_project_root / "agents" / "enterprise" / "policy_agent" / "skill")
)
QUALITY_THRESHOLD = float(os.getenv("LOAD_TEST_THRESHOLD", str(_baselines.get("quality_threshold", 0.8))))
LATENCY_BUDGET_MS = int(os.getenv("LOAD_TEST_LATENCY_BUDGET_MS", str(int(_baselines.get("p95_latency_ms", 30000)))))
ERROR_RATE_BUDGET = _baselines.get("error_rate", 0.0)
REPORT_PATH = EVAL_DIR.parent / "load_test_report.json"


# ---------------------------------------------------------------------------
# Agent setup (same pattern as test_eval.py)
# ---------------------------------------------------------------------------


def _build_local_supervisor() -> Agent:
    """Build supervisor with local sub-agents using the production prompt."""
    policy_agent = create_policy_agent(model_id=MODEL_ID)
    hr_calculator = Agent(
        name="hr_calculator",
        model=Gemini(model=MODEL_ID),
        description=(
            "A remote agent that calculates PTO balances, sick leave balances, "
            "working days for specific date ranges, and remaining work days in a "
            "month/quarter/year."
        ),
        instruction=(
            "You calculate PTO balances, working days, and leave details. "
            "Use your tools to get data before answering."
        ),
        tools=[
            calculate_pto_details,
            calculate_working_days_for_period,
            get_remaining_working_days,
        ],
    )
    return Agent(
        name="knowledge_supervisor",
        model=Gemini(model=MODEL_ID),
        description="A supervisor agent that coordinates other agents to answer user queries.",
        instruction=SUPERVISOR_INSTRUCTION,
        sub_agents=[policy_agent, hr_calculator],
    )


# ---------------------------------------------------------------------------
# Run + score
# ---------------------------------------------------------------------------


_QUOTA_MARKERS = ("RESOURCE_EXHAUSTED", "429")
_QUOTA_RETRIES = 3
_QUOTA_BACKOFF_S = 20


async def _run_question(supervisor: Agent, question: str, topic: str) -> dict:
    """Run a question with backoff on Vertex quota errors (429s).

    CI runs this job alongside the golden eval against the same project
    quota; transient RESOURCE_EXHAUSTED responses are contention noise and
    would otherwise pollute both the error-rate budget and the quality score.
    """
    for attempt in range(1, _QUOTA_RETRIES + 1):
        result = await _run_question_once(supervisor, question, topic)
        error = result["error"] or ""
        if attempt < _QUOTA_RETRIES and any(m in error for m in _QUOTA_MARKERS):
            delay = _QUOTA_BACKOFF_S * attempt
            logger.warning(
                "Quota error on %r (attempt %d/%d); retrying in %ds",
                question, attempt, _QUOTA_RETRIES, delay,
            )
            await asyncio.sleep(delay)
            continue
        return result
    return result


async def _run_question_once(supervisor: Agent, question: str, topic: str) -> dict:
    """Run a question through the supervisor and collect the response."""
    app = App(root_agent=supervisor, name="load_test")
    session_service = InMemorySessionService()
    runner = Runner(app=app, session_service=session_service, auto_create_session=True)

    user_id = f"load_{uuid.uuid4().hex[:8]}"
    session_id = f"load_{uuid.uuid4().hex[:8]}"

    start = time.monotonic()
    response_text = ""
    agents_invoked = set()
    tools_called = set()
    error = None

    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=types.Content(
                role="user",
                parts=[types.Part.from_text(text=question)],
            ),
        ):
            if event.author and event.author != "user":
                agents_invoked.add(event.author)
            if event.content and not event.partial:
                for part in event.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        tools_called.add(part.function_call.name)
                    if part.text and event.author != "user":
                        response_text = part.text
    except Exception as e:
        error = str(e)

    latency_ms = (time.monotonic() - start) * 1000

    return {
        "question": question,
        "topic": topic,
        "response": response_text[:1000],
        "latency_ms": round(latency_ms, 1),
        "agents_invoked": sorted(agents_invoked),
        "tools_called": sorted(tools_called),
        "error": error,
    }


async def _generate_and_run(supervisor: Agent, count: int) -> list[dict]:
    """Generate fresh questions, run through supervisor, judge with LLM."""
    from eval.scoring.llm_judge import judge_response, load_scope_context

    # Topics that V1 supervisor prompt routes correctly. Expenses, benefits,
    # and holidays are intentionally excluded — V1 doesn't route those to
    # policy_agent, so they fail. The quality agent detects those failures
    # and the remediation agent fixes the prompt.
    all_topics = [
        "pto", "sick_leave", "remote_work",
    ]
    per_topic = max(1, count // len(all_topics))
    remainder = count - per_topic * len(all_topics)
    topics = parse_topics_config(
        ",".join(
            f"{t}:{per_topic + (1 if i < remainder else 0)}"
            for i, t in enumerate(all_topics)
        )
    )
    # OOS detection is the quality agent's job. The load test is a regression
    # gate — it verifies in-scope topics still work after a prompt change.
    questions = await generate_all_questions(topics, include_out_of_scope=False)

    # Phase 1: Run all questions through the agent
    results = []
    for q in questions:
        result = await _run_question(
            supervisor, q["question"], q.get("topic", "unknown")
        )
        results.append(result)

    # Phase 2: Judge all responses with LLM
    scope_context = load_scope_context()
    for r in results:
        if r["error"]:
            r["judge"] = {"category": "unhelpful", "reason": f"Runtime error: {r['error']}"}
        else:
            r["judge"] = await judge_response(
                r["question"], r["response"], scope_context
            )
        r["meaningful"] = r["judge"]["category"] in ("meaningful", "declined")

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _save_report(results: list[dict]) -> dict:
    """Save results to JSON and return the summary."""
    from collections import Counter

    verdicts = Counter(r["judge"]["category"] for r in results)
    meaningful = sum(1 for r in results if r["meaningful"])
    errors = sum(1 for r in results if r["error"])
    # Exclude errored questions from latency stats (crash latency is meaningless)
    latencies = sorted(r["latency_ms"] for r in results if not r["error"])
    p95_idx = min(int(len(latencies) * 0.95), len(latencies) - 1) if latencies else 0

    summary = {
        "total": len(results),
        "meaningful": meaningful,
        "verdicts": dict(verdicts),
        "errors": errors,
        "error_rate": round(errors / len(results), 3) if results else 0,
        "meaningful_rate": round(meaningful / len(results) * 100, 1) if results else 0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "p95_latency_ms": round(latencies[p95_idx], 1) if latencies else 0,
    }

    report = {"summary": summary, "results": results}
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)

    return summary


# ---------------------------------------------------------------------------
# Module-level cache (generate + run once, share across all tests)
# ---------------------------------------------------------------------------

_cached_results = None
_cached_summary = None


def _ensure_results():
    """Generate and run traffic once, cache for all tests."""
    global _cached_results, _cached_summary
    if _cached_results is not None:
        return _cached_results, _cached_summary

    supervisor = _build_local_supervisor()
    _cached_results = asyncio.run(_generate_and_run(supervisor, COUNT))
    _cached_summary = _save_report(_cached_results)

    # Print summary to stdout so pytest -v shows it
    verdicts = _cached_summary.get("verdicts", {})
    breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(verdicts.items()))
    print(f"\n  Load test: {_cached_summary['meaningful']}/{_cached_summary['total']} "
          f"meaningful ({_cached_summary['meaningful_rate']}%), "
          f"P95 latency {_cached_summary['p95_latency_ms']}ms\n"
          f"  Verdicts: {breakdown}")

    return _cached_results, _cached_summary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def load_results():
    results, _ = _ensure_results()
    return results


@pytest.fixture(scope="module")
def load_summary():
    _, summary = _ensure_results()
    return summary


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    _BASELINE_POLICY,
    reason="The V0 baseline policy skill (version 0) answers from baked facts "
    "and defers everything else to HR — the deliberate defect the evolution "
    "loop repairs via PRs. Hard-asserted once the skill carries version >= 1.",
    strict=False,
)
def test_quality_threshold(load_results, load_summary):
    """Fresh traffic should meet quality threshold (baselines.json: quality_threshold)."""
    rate = load_summary["meaningful"] / load_summary["total"]

    failed = [r for r in load_results if not r["meaningful"] and not r.get("error")]
    details = "\n".join(
        f"  [{r['topic']}] {r['question']}\n"
        f"    Verdict: {r['judge']['category']} — {r['judge']['reason']}\n"
        f"    Response: {r['response'][:200]}"
        for r in failed[:5]
    )

    verdicts = load_summary.get("verdicts", {})
    breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(verdicts.items()))

    assert rate >= QUALITY_THRESHOLD, (
        f"Quality {rate:.0%} below threshold {QUALITY_THRESHOLD:.0%}.\n"
        f"Meaningful: {load_summary['meaningful']}/{load_summary['total']}\n"
        f"Verdicts: {breakdown}\n"
        f"Failed questions:\n{details}"
    )


def test_error_rate(load_results, load_summary):
    """Error rate should be within budget (baselines.json: error_rate)."""
    error_rate = load_summary["error_rate"]
    errors = [r for r in load_results if r["error"]]
    assert error_rate <= ERROR_RATE_BUDGET, (
        f"Error rate {error_rate:.1%} exceeds budget {ERROR_RATE_BUDGET:.1%}.\n"
        f"{len(errors)} error(s):\n"
        + "\n".join(f"  {r['question']}: {r['error']}" for r in errors)
    )


def test_latency_budget(load_results):
    """P95 latency should be within budget (baselines.json: p95_latency_ms)."""
    latencies = sorted(r["latency_ms"] for r in load_results if not r["error"])
    if not latencies:
        pytest.skip("No successful results to measure latency")
    p95_idx = min(int(len(latencies) * 0.95), len(latencies) - 1)
    p95 = latencies[p95_idx]

    assert p95 <= LATENCY_BUDGET_MS, (
        f"P95 latency {p95:.0f}ms exceeds budget {LATENCY_BUDGET_MS}ms"
    )


@pytest.mark.xfail(
    _BASELINE_POLICY,
    reason="quality_threshold sits inside the budget set, so the composite "
    "check inherits the V0 baseline xfail above; operational-only budgets "
    "stay covered by test_error_rate and test_latency_budget.",
    strict=False,
)
def test_budget_baselines(load_summary):
    """All metrics should be within baselines.json budgets."""
    from eval.scoring.check_budget import check_budgets, load_baselines

    baselines = load_baselines()
    if not baselines:
        pytest.skip("No baselines.json found")

    all_pass, failures = check_budgets(load_summary, baselines)
    assert all_pass, (
        "Budget baseline(s) exceeded:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )
