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

"""Eval regression tests for the Knowledge Supervisor.

Runs each case in eval_cases.json through a local supervisor (with local
sub-agents, no remote A2A) and checks:

  - Routing: the expected sub-agent was invoked.
  - Tool use: the expected tool was called.
  - Out-of-scope: questions that should be declined are not routed.

Usage:
    pytest eval/test_eval.py -v
    pytest eval/test_eval.py -k "pto"        # run one case
    pytest eval/test_eval.py -x              # stop on first failure
"""

import json
import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

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

# Import sub-agent definitions directly (local, no A2A)
from agents.enterprise.knowledge_supervisor.app.prompts import SUPERVISOR_INSTRUCTION
from agents.enterprise.policy_agent.agent import create_agent as create_policy_agent
from agents.enterprise.hr_calculator.agent import (
    calculate_pto_details,
    calculate_working_days_for_period,
    get_remaining_working_days,
)

EVAL_DIR = Path(__file__).parent
MODEL_ID = os.getenv("EVAL_MODEL_ID", "gemini-2.5-flash")

# The production-loop demo keeps a deliberately flawed V0 supervisor skill on
# main (baked policy summary, defers to HR); evolution PRs replace it with a
# version >= 1 skill. Assertions that require evolved behavior (compound
# fan-out) xfail non-strictly while the baseline is active and hard-assert on
# evolution PRs.
from agents.enterprise.policy_agent.skill_loader import skill_is_baseline  # noqa: E402

_SUPERVISOR_SKILL_DIR = str(
    _project_root / "agents" / "enterprise" / "knowledge_supervisor" / "app" / "skill"
)
_BASELINE_SUPERVISOR = skill_is_baseline(_SUPERVISOR_SKILL_DIR)


# Reuse the ONE canonical builder (traffic_generator) so the gate tests exactly
# the topology + skills the demo evolves: a 3-agent AgentTool supervisor that
# loads each agent's SKILL.md (PROMPT_MODE=skill-evolution). A second, drifting
# copy here previously used prompts.py, omitted the benefits agent, and used the
# sub_agents handoff model -- so it could neither route to benefits nor fan out on
# compound questions, and it never exercised the evolved skill.
from agents.workflow.traffic_generator.main import (  # noqa: E402
    _build_local_supervisor,
)


# ---------------------------------------------------------------------------
# Load eval cases
# ---------------------------------------------------------------------------


def _load_eval_cases() -> list[dict]:
    with open(EVAL_DIR.parent / "data" / "eval_cases.json") as f:
        data = json.load(f)
    return data.get("eval_cases", data)


EVAL_CASES = _load_eval_cases()


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------


async def _run_agent(supervisor: Agent, question: str) -> dict:
    """Run a question through the supervisor and collect events."""
    app = App(root_agent=supervisor, name="eval_test")
    session_service = InMemorySessionService()
    runner = Runner(app=app, session_service=session_service, auto_create_session=True)

    user_id = f"eval_{uuid.uuid4().hex[:8]}"
    session_id = f"eval_{uuid.uuid4().hex[:8]}"

    agents_invoked = set()
    tools_called = set()
    response_text = ""

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

    return {
        "agents_invoked": agents_invoked,
        "tools_called": tools_called,
        "response_text": response_text,
    }


# ---------------------------------------------------------------------------
# Parametrized tests
# ---------------------------------------------------------------------------


# Function-scoped (not module-scoped): pytest-asyncio runs each async test in
# its own event loop, but the supervisor's Gemini models bind their async client
# to the loop that is live when first used. A module-scoped fixture would reuse
# those clients across tests, so every test after the first hit "Event loop is
# closed". Rebuilding per test keeps each model's client on its own test's loop.
@pytest.fixture
def supervisor():
    # In-process 3-agent supervisor (policy + benefits + hr_calculator), the same
    # topology the evolution demo builds. Avoids a dependency on deployed Cloud Run
    # services in CI and is the only build that wires the benefits specialist.
    return _build_local_supervisor(local_agents=True)


@pytest.mark.xfail(
    _BASELINE_SUPERVISOR,
    reason="The V0 baseline supervisor (version 0) carries the deliberate "
    "deflect-to-HR defect, so whether it routes or deflects on any given "
    "run is nondeterministic (observed 0-3 flakes per run). Hard-asserted "
    "once the skill carries version >= 1.",
    strict=False,
)
@pytest.mark.parametrize(
    "case",
    [c for c in EVAL_CASES if c.get("expected_agent")],
    ids=[c["id"] for c in EVAL_CASES if c.get("expected_agent")],
)
@pytest.mark.asyncio
async def test_routing(supervisor, case):
    """Verify the supervisor routes to the expected sub-agent.

    A specialist can be reached two ways: a handoff (sub_agents -> event.author)
    or an AgentTool call (function_call whose name IS the agent name). Accept
    either, so the test is agnostic to the supervisor's wiring.
    """
    result = await _run_agent(supervisor, case["question"])
    reached = result["agents_invoked"] | result["tools_called"]

    assert case["expected_agent"] in reached, (
        f"Expected agent '{case['expected_agent']}' not reached. "
        f"Agents invoked: {result['agents_invoked']}, tools: {result['tools_called']}\n"
        f"Question: {case['question']}"
    )


@pytest.mark.parametrize(
    "case",
    [c for c in EVAL_CASES if c.get("expected_tool")],
    ids=[c["id"] for c in EVAL_CASES if c.get("expected_tool")],
)
@pytest.mark.asyncio
async def test_tool_use(supervisor, case):
    """Verify the expected tool was called."""
    result = await _run_agent(supervisor, case["question"])

    assert case["expected_tool"] in result["tools_called"], (
        f"Expected tool '{case['expected_tool']}' not called. "
        f"Tools called: {result['tools_called']}\n"
        f"Question: {case['question']}"
    )


@pytest.mark.xfail(
    _BASELINE_SUPERVISOR,
    reason="The V0 baseline supervisor skill (version 0) answers compound "
    "questions from its baked policy summary, so specialist fan-out is a "
    "known defect the evolution loop repairs via PRs. Hard-asserted once "
    "the skill carries version >= 1.",
    strict=False,
)
@pytest.mark.parametrize(
    "case",
    [c for c in EVAL_CASES if c.get("expected_agents")],
    ids=[c["id"] for c in EVAL_CASES if c.get("expected_agents")],
)
@pytest.mark.asyncio
async def test_compound(supervisor, case):
    """Compound cross-domain: the supervisor must invoke EVERY expected
    specialist in a single turn (fan-out + synthesize), not just one."""
    result = await _run_agent(supervisor, case["question"])
    reached = result["agents_invoked"] | result["tools_called"]

    missing = [a for a in case["expected_agents"] if a not in reached]
    assert not missing, (
        f"Compound question did not reach all specialists. "
        f"Missing: {missing}. Reached: {reached}\n"
        f"Question: {case['question']}"
    )


@pytest.mark.xfail(
    reason="Clean out-of-scope decline is a known, tracked gap: the agent soft-fails "
    "('I couldn't find that, contact HR') instead of cleanly declining. Routed to "
    "PRODUCT in the triage backlog (scope allow/deny list). Non-strict: flip to a "
    "hard assert once the scope policy lands.",
    strict=False,
)
@pytest.mark.parametrize(
    "case",
    [c for c in EVAL_CASES if c.get("expected_behavior") == "decline_gracefully"],
    ids=[c["id"] for c in EVAL_CASES if c.get("expected_behavior") == "decline_gracefully"],
)
@pytest.mark.asyncio
async def test_out_of_scope(supervisor, case):
    """Verify out-of-scope questions are declined (LLM judge)."""
    from eval.scoring.llm_judge import judge_response, load_scope_context

    result = await _run_agent(supervisor, case["question"])
    verdict = await judge_response(
        case["question"],
        result["response_text"],
        load_scope_context(),
    )

    assert verdict["category"] == "declined", (
        f"Out-of-scope question not declined.\n"
        f"Question: {case['question']}\n"
        f"Verdict: {verdict['category']} — {verdict['reason']}\n"
        f"Response: {result['response_text'][:200]}"
    )
