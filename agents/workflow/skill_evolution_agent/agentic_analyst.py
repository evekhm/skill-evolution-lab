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

"""Agentic error analysts with tool access for investigation.

Upgrades the single-pass error analyst to a multi-turn investigator that
can call lookup_company_policy() to verify hypotheses before proposing
patches. Inspired by Trace2Skill's agentic investigation loop.

Usage:
    from agents.workflow.skill_evolution_agent.agentic_analyst import run_agentic_analyst

    patch = run_agentic_analyst(client, model_id, session, current_skill)
"""

import json
import logging
import os
import sys

from google import genai
from google.genai import types

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, PROJECT_ROOT)

from agents.enterprise.policy_agent.tools import get_current_date, lookup_company_policy
from agents.workflow.skill_evolution_agent.evolve import format_trajectory

logger = logging.getLogger(__name__)

AGENTIC_ERROR_ANALYST_PROMPT = """\
You are an Agentic Error Analyst investigating a failed agent trajectory.
Unlike a passive analyst, you have access to the agent's tools and can
ACTIVELY INVESTIGATE what went wrong.

Your investigation process:
1. Read the failed trajectory carefully
2. Form a hypothesis about the root cause
3. USE THE TOOLS to verify your hypothesis:
   - Call lookup_company_policy() with the topic the user asked about
   - Try different keyword variations to see what works/fails
   - Check what data the tool actually returns
4. Compare tool output with what the agent said
5. Propose a specific, evidence-based patch

You have access to:
- lookup_company_policy(topic): Look up company policy. Topics: pto,
  sick_leave, remote_work, expenses, benefits, holidays
- get_current_date(): Get today's date

INVESTIGATION STRATEGY:
- Start by calling the tool with the EXACT keyword the user used
- Then try the keyword the agent SHOULD have used
- Note any gaps between user language and tool topics
- Check if the tool's response matches what the agent said

After investigation, output your patch in this format:

## Root Cause
[CATEGORY]: [one-line description]

Categories: TOOL_USAGE, WRONG_TOOL, MISSING_RULE, AMBIGUITY, SCOPE_GAP,
HALLUCINATION, PARROTING, CORRECTION_IGNORE

## Investigation Evidence
[What you found by calling the tools -- specific data points]

## Analysis
[2-3 sentences explaining root cause with evidence from investigation]

## Proposed Patch
Section: [which section of the skill to modify]
Action: add_rule | add_edge_case | add_anti_pattern
Content:
[The exact text to add. A behavioral rule, not a fact. Must generalize.]

RULES:
- You MUST call at least one tool before proposing a patch
- Base your patch on EVIDENCE, not speculation
- Propose patches that GENERALIZE beyond this single trajectory
- Patches must be BEHAVIORAL (how to act), never baked facts. Do NOT
  propose keyword or synonym mappings -- the lookup tool resolves the
  user's wording itself; a missing fact a tool could fetch is a
  TOOL_USAGE fix (a rule to call the tool)
- If the failure has no generalizable fix, output "NO_PATCH: [reason]"
"""

# Tool declarations for Gemini function calling
INVESTIGATION_TOOL_DECLARATIONS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="lookup_company_policy",
            description=(
                "Look up a company policy by topic. Available topics: "
                "pto, sick_leave, remote_work, expenses, benefits, holidays. "
                "You can also try user-language keywords to test mappings."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "topic": {
                        "type": "STRING",
                        "description": "The policy topic to look up",
                    }
                },
                "required": ["topic"],
            },
        ),
        types.FunctionDeclaration(
            name="get_current_date",
            description="Get the current date and day of the week.",
            parameters={
                "type": "OBJECT",
                "properties": {},
            },
        ),
    ]
)

# Map of callable functions
TOOL_FUNCTIONS = {
    "lookup_company_policy": lookup_company_policy,
    "get_current_date": get_current_date,
}


def _execute_tool_call(function_call) -> dict:
    """Execute a tool call and return the result as a dict."""
    name = function_call.name
    args = dict(function_call.args) if function_call.args else {}

    func = TOOL_FUNCTIONS.get(name)
    if not func:
        return {"error": f"Unknown function: {name}"}

    try:
        result = func(**args)
        if isinstance(result, str):
            return {"result": result}
        return result
    except Exception as e:
        return {"error": str(e)}


def run_agentic_analyst(
    client: genai.Client,
    model_id: str,
    session: dict,
    current_skill: str,
    max_turns: int = 5,
) -> str | None:
    """Run an agentic error analyst with tool access.

    The analyst can call lookup_company_policy() and get_current_date()
    to verify its hypotheses before proposing a patch. This produces
    higher-quality, evidence-based patches compared to single-pass analysis.

    Args:
        client: Genai client.
        model_id: Model for analyst calls.
        session: Failed session from quality report.
        current_skill: Current SKILL.md content.
        max_turns: Max investigation turns (tool calls).

    Returns:
        Patch text or None if no patch proposed.
    """
    trajectory = format_trajectory(session)
    question = session.get("question", "")[:60]

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(
                text=(
                    f"<current_skill>\n{current_skill}\n</current_skill>\n\n"
                    f"<trajectory>\n{trajectory}\n</trajectory>\n\n"
                    "Investigate this failure. Use the tools to verify your "
                    "hypotheses before proposing a patch."
                )
            )]
        )
    ]

    tool_calls = 0
    for turn in range(max_turns + 1):
        response = client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=AGENTIC_ERROR_ANALYST_PROMPT,
                tools=[INVESTIGATION_TOOL_DECLARATIONS],
                temperature=0.3,
            ),
        )

        # Check response parts for function calls
        response_parts = response.candidates[0].content.parts
        function_call_parts = [
            p for p in response_parts
            if hasattr(p, "function_call") and p.function_call
        ]

        if not function_call_parts:
            # Model returned final text — the patch
            text = response.text.strip() if response.text else None
            if text and "NO_PATCH" in text and len(text) < 200:
                logger.info(
                    "  [agentic] %s -> no patch (%d tool calls)",
                    question, tool_calls,
                )
                return None
            logger.info(
                "  [agentic] %s -> patch (%d tool calls)",
                question, tool_calls,
            )
            return text

        # Add model's response (with function calls) to conversation
        contents.append(response.candidates[0].content)

        # Execute all function calls and build response parts
        fn_response_parts = []
        for part in function_call_parts:
            fc = part.function_call
            result = _execute_tool_call(fc)
            tool_calls += 1
            logger.debug(
                "  [agentic] %s called %s(%s) -> %s",
                question, fc.name,
                dict(fc.args) if fc.args else {},
                str(result)[:100],
            )
            fn_response_parts.append(
                types.Part.from_function_response(
                    name=fc.name,
                    response=result,
                )
            )

        contents.append(types.Content(
            role="user",
            parts=fn_response_parts,
        ))

    # Max turns exhausted
    logger.warning("  [agentic] %s -> max turns reached", question)
    return response.text.strip() if response.text else None
