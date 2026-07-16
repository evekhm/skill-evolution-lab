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

"""LLM-as-judge for evaluating agent response quality.

Uses the same categories as quality_report.py:
  meaningful, declined, unhelpful, partial.

Usage (async):
    from eval.scoring.llm_judge import judge_response, load_scope_context

    scope_ctx = load_scope_context()
    verdict = await judge_response(question, response, scope_ctx)
    # verdict = {"category": "meaningful", "reason": "..."}

Usage (sync):
    from eval.scoring.llm_judge import judge_response_sync, load_scope_context

    scope_ctx = load_scope_context()
    verdict = judge_response_sync(question, response, scope_ctx)
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from google.genai import Client
from google.genai import types
from pydantic import BaseModel

logger = logging.getLogger(__name__)

EVAL_DIR = Path(__file__).parent
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gemini-2.5-flash")

# Valid verdict categories
VALID_CATEGORIES = ("meaningful", "declined", "unhelpful", "partial")


class JudgeVerdict(BaseModel):
    """Structured output schema for the LLM judge."""
    category: str
    reason: str


JUDGE_PROMPT = """\
You are an LLM judge evaluating an AI agent's response quality.

Given a user QUESTION and the agent's RESPONSE, classify the response into
exactly one category:

- **meaningful**: The response directly and substantively addresses the question
  with specific, actionable information.
- **declined**: The question is outside the agent's scope and the agent correctly
  declined (e.g. said it cannot help with that topic). This is CORRECT behavior
  for out-of-scope questions.
- **unhelpful**: The response does NOT meaningfully answer the question AND the
  question IS within the agent's scope. Examples: apologies for in-scope topics,
  saying "I do not have that information" when the agent should have tools to
  answer, empty data, generic filler, or looping without resolution.
- **partial**: The response partially addresses the question but is incomplete
  or missing key details.

The agent handles: PTO, sick leave, remote work, expenses, benefits, holidays,
and HR calculations (PTO balance, working days).{scope_context}

QUESTION: {question}

RESPONSE: {response}

Respond with the category and a brief reason.
"""


def load_scope_context() -> str:
    """Build scope context string from agent_context.json."""
    ctx_path = EVAL_DIR.parent / "data" / "agent_context.json"
    if not ctx_path.exists():
        return ""
    with open(ctx_path) as f:
        ctx = json.load(f)
    oos = [
        d["topic"]
        for d in ctx.get("scope_decisions", [])
        if d.get("decision") == "out_of_scope"
    ]
    if not oos:
        return ""
    return (
        f"\n\nOut-of-scope topics (declining these is CORRECT): "
        f"{', '.join(t.replace('_', ' ') for t in oos)}."
    )


def _get_client() -> Client:
    """Create a Gemini client."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    return Client(project=project, location=location)


async def judge_response(
    question: str,
    response: str,
    scope_context: str = "",
    client: Client | None = None,
) -> dict:
    """Use LLM to judge a response. Returns {"category": ..., "reason": ...}."""
    if client is None:
        client = _get_client()

    prompt = JUDGE_PROMPT.format(
        question=question,
        response=response[:1000],
        scope_context=scope_context,
    )
    try:
        result = await asyncio.to_thread(
            client.models.generate_content,
            model=JUDGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=JudgeVerdict,
                temperature=0.0,
            ),
        )
        data = json.loads(result.text)
        category = data.get("category", "unhelpful").lower()
        if category not in VALID_CATEGORIES:
            category = "unhelpful"
        return {"category": category, "reason": data.get("reason", "")}
    except Exception as e:
        logger.warning("Judge call failed: %s", e)
        return {"category": "unhelpful", "reason": f"Judge error: {e}"}


def judge_response_sync(
    question: str,
    response: str,
    scope_context: str = "",
) -> dict:
    """Synchronous wrapper for judge_response."""
    return asyncio.run(judge_response(question, response, scope_context))
