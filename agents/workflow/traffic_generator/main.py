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

"""Traffic generator and runner for the Knowledge Supervisor.

Generates synthetic questions and runs them against the agent (local or deployed).

Usage:
    # Generate + run locally (one step):
    python agents/workflow/traffic_generator/main.py --local --count 10

    # Generate + run against deployed agent:
    python agents/workflow/traffic_generator/main.py --count 10

    # Generate only (save to file):
    python agents/workflow/traffic_generator/main.py --generate-only --count 10 --output traffic.json

    # Run from file (local):
    python agents/workflow/traffic_generator/main.py --local --from-file traffic.json

    # Run from file (deployed):
    python agents/workflow/traffic_generator/main.py --from-file traffic.json

    # CI mode (local + budget enforcement):
    python agents/workflow/traffic_generator/main.py --local --from-file traffic.json --fail-on-budget
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import threading
import time
import uuid

import google.auth
from google.genai import Client
from google.genai import types
from pydantic import BaseModel
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("traffic_generator")

# One run_id per generator invocation - stamps every event this run
# produces so evolution can select exactly this slice of traces.
_RUN_ID = time.strftime("%Y%m%d-%H%M%S")

env_path = os.path.join(os.path.dirname(__file__), "../../../.env")
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path, override=False)

_, project_id = google.auth.default()
PROJECT_ID = os.getenv("PROJECT_ID", project_id)
REGION = os.getenv("REGION", "us-central1")
# Model calls may need a different endpoint than the infra region:
# gemini-3.x models are served from the global endpoint only.
MODEL_LOCATION = (
    os.getenv("MODEL_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "global"
)

os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = MODEL_LOCATION
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------


class QuestionList(BaseModel):
    questions: list[str]


TOPIC_CAPABILITIES = {
    "pto": (
        "The agent can answer: PTO balance, accrual rate, rollover policy, "
        "advance notice requirements for time off requests. "
        "It can also calculate current PTO balance, sick leave balance, "
        "working days for specific date ranges, and remaining working days."
    ),
    "sick_leave": (
        "The agent can answer: sick days per year, rollover policy, "
        "doctor's note requirements, what sick leave covers."
    ),
    "remote_work": (
        "The agent can answer: remote work days per week, approval "
        "requirements, core hours, equipment stipend."
    ),
    "expenses": (
        "The agent can answer: expense submission deadlines, meal limits, "
        "receipt thresholds, travel pre-approval requirements."
    ),
    "benefits": (
        "The agent can answer: health/dental/vision insurance details, "
        "401k matching, parental leave, education reimbursement."
    ),
    "holidays": (
        "The agent can answer: company holidays, holiday dates, "
        "total paid holidays per year, next upcoming holiday."
    ),
    "company policies": (
        "The agent can answer questions about any company policy: PTO, "
        "sick leave, remote work, expenses, benefits, and holidays. "
        "It can also calculate PTO balances and working days."
    ),
}


def _load_agent_context() -> dict:
    """Load agent_context.json for scope decisions."""
    ctx_path = os.path.join(
        os.path.dirname(__file__), "../../../eval/data/agent_context.json"
    )
    if not os.path.isfile(ctx_path):
        return {}
    with open(ctx_path) as f:
        return json.load(f)


def _get_out_of_scope_topics() -> list[str]:
    """Return out-of-scope topic names from agent_context.json."""
    ctx = _load_agent_context()
    return [
        d["topic"]
        for d in ctx.get("scope_decisions", [])
        if d.get("decision") == "out_of_scope"
    ]


def _get_capability_description(topic: str) -> str:
    """Match topic to known capability descriptions."""
    topic_lower = topic.lower()
    for key, desc in TOPIC_CAPABILITIES.items():
        if key in topic_lower:
            return desc
    keyword_map = {
        "paid time off": "pto",
        "vacation": "pto",
        "time off": "pto",
        "leave": "pto",
        "working days": "pto",
        "medical": "sick_leave",
        "illness": "sick_leave",
        "doctor": "sick_leave",
        "work from home": "remote_work",
        "wfh": "remote_work",
        "hybrid": "remote_work",
        "travel": "expenses",
        "reimbursement": "expenses",
        "receipt": "expenses",
        "health": "benefits",
        "insurance": "benefits",
        "401k": "benefits",
        "parental": "benefits",
        "dental": "benefits",
        "vision": "benefits",
    }
    for keyword, cap_key in keyword_map.items():
        if keyword in topic_lower:
            return TOPIC_CAPABILITIES[cap_key]
    return TOPIC_CAPABILITIES["company policies"]


async def generate_questions(client: Client, topic: str, count: int) -> list[str]:
    """Uses Gemini to generate realistic test questions."""
    logger.info(f"Generating {count} questions about topic: '{topic}'...")

    capability = _get_capability_description(topic)

    prompt = (
        f"Generate {count} diverse and realistic questions that a user might ask an AI assistant "
        f"about the topic: '{topic}'.\n\n"
        f"The agent has these specific capabilities for this topic:\n{capability}\n\n"
        f"IMPORTANT: Only generate questions that the agent CAN answer using these capabilities. "
        f"Generate practical, answerable questions. Vary the phrasing."
    )

    try:
        response = client.models.generate_content(
            model=os.getenv("EVAL_MODEL_ID", "gemini-3.5-flash"),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=QuestionList,
                temperature=0.7,
            ),
        )

        data = json.loads(response.text)
        questions = data.get("questions", [])
        return questions[:count]
    except Exception as e:
        logger.info(f"Error generating questions: {e}")
        return [
            f"Tell me about {topic}",
            f"What information can you provide about {topic}?",
            f"What is the company policy on {topic}?",
        ][:count]


def parse_topics_config(topics_config_str: str) -> dict[str, int]:
    """Parse 'topic:count,topic:count' string into dict."""
    topics = {}
    try:
        for item in topics_config_str.split(","):
            if ":" in item:
                topic, count = item.rsplit(":", 1)
                topics[topic.strip()] = int(count.strip())
    except Exception as e:
        logger.warning(f"Failed to parse TOPICS_CONFIG: {e}. Using default.")
        topics = {"company policies": 3}
    return topics


def _topics_from_count(count: int) -> str:
    """Distribute count evenly across main topics."""
    topics = ["pto", "benefits", "expenses", "holidays", "sick_leave"]
    per_topic = max(1, count // len(topics))
    remainder = count - per_topic * len(topics)
    return ",".join(
        f"{t}:{per_topic + (1 if i < remainder else 0)}" for i, t in enumerate(topics)
    )


async def generate_out_of_scope_questions(
    client: Client, topics: list[str], count: int
) -> list[str]:
    """Generate realistic questions about out-of-scope topics."""
    if not topics:
        return []
    logger.info(f"Generating {count} out-of-scope questions for: {topics}")
    prompt = (
        f"Generate {count} diverse, realistic questions that a user might ask an HR assistant "
        f"about the following topics: {', '.join(t.replace('_', ' ') for t in topics)}.\n\n"
        f"These are topics the agent CANNOT answer. Generate natural questions a user "
        f"would genuinely ask, not trick questions. Vary phrasing and specificity."
    )
    try:
        response = client.models.generate_content(
            model=os.getenv("EVAL_MODEL_ID", "gemini-3.5-flash"),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=QuestionList,
                temperature=0.7,
            ),
        )
        data = json.loads(response.text)
        return data.get("questions", [])[:count]
    except Exception as e:
        logger.warning(f"Error generating out-of-scope questions: {e}")
        return [
            f"What can you tell me about {t.replace('_', ' ')}?" for t in topics[:count]
        ]


async def generate_all_questions(
    topics_config: dict[str, int], include_out_of_scope: bool = True
) -> list[dict]:
    """Generate questions for all topics. Returns list of {question, topic}.

    Args:
        topics_config: In-scope topics with counts.
        include_out_of_scope: If True (default), also generate questions for
            out-of-scope topics from agent_context.json (~10% of total).
    """
    genai_client = Client(project=PROJECT_ID, location=MODEL_LOCATION)

    all_questions = []
    for topic, count in topics_config.items():
        questions = await generate_questions(genai_client, topic, count)
        for q in questions:
            all_questions.append({"question": q, "topic": topic})

    if include_out_of_scope:
        oos_topics = _get_out_of_scope_topics()
        if oos_topics:
            total_in_scope = len(all_questions)
            oos_count = max(1, total_in_scope // 10)
            oos_questions = await generate_out_of_scope_questions(
                genai_client, oos_topics, oos_count
            )
            for q in oos_questions:
                all_questions.append({"question": q, "topic": "out_of_scope"})

    return all_questions


# ---------------------------------------------------------------------------
# Format conversion and I/O
# ---------------------------------------------------------------------------


def _load_golden_questions() -> list[str]:
    """Load questions from golden eval set for dedup."""
    eval_path = os.path.join(os.path.dirname(__file__), "../../../eval/data/eval_cases.json")
    if not os.path.isfile(eval_path):
        return []
    with open(eval_path) as f:
        data = json.load(f)
    return [c["question"] for c in data.get("eval_cases", [])]


def _to_eval_format(questions: list[dict]) -> dict:
    """Convert questions to eval_cases format with dedup against golden set."""
    existing_lower = {q.lower() for q in _load_golden_questions()}

    eval_cases = []
    for i, q in enumerate(questions):
        text = q["question"]
        if text.lower() in existing_lower:
            continue
        topic = q.get("topic", "unknown")
        category = topic.replace(" ", "_").lower()
        for key in (
            "pto",
            "sick_leave",
            "remote_work",
            "expenses",
            "benefits",
            "holidays",
        ):
            if key in category:
                category = key
                break
        else:
            if category not in ("out_of_scope",):
                category = "general"

        eval_cases.append(
            {
                "id": f"traffic_{i+1:03d}",
                "question": text,
                "category": category,
            }
        )

    return {
        "eval_set_id": "synthetic_traffic",
        "name": "Synthetic User Traffic",
        "description": "Auto-generated by Gemini to simulate real user questions.",
        "eval_cases": eval_cases,
    }


def save_questions(
    questions: list[dict], output_path: str, eval_format: bool = False
) -> None:
    """Save generated questions to a JSON file."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if eval_format:
        data = _to_eval_format(questions)
    else:
        data = {"questions": questions}
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    count = len(data.get("eval_cases", data.get("questions", [])))
    logger.info(f"Saved {count} questions to {output_path}")


def load_questions(input_path: str) -> list[dict]:
    """Load questions from a JSON file. Supports both formats."""
    with open(input_path) as f:
        data = json.load(f)
    # Support eval_cases format and questions format
    raw = data.get("eval_cases", data.get("questions", []))
    normalized = []
    for q in raw:
        if isinstance(q, str):
            normalized.append({"question": q, "topic": "unknown"})
        elif isinstance(q, dict):
            # Scripted multi-turn: "turns" carries the exact user messages
            # (e.g. correction-bait pushback); turns[0] is the opening question.
            turns = q.get("turns")
            entry = {
                "question": q.get("question") or (turns[0] if turns else ""),
                "topic": q.get("topic", q.get("category", "unknown")),
            }
            if turns:
                entry["turns"] = turns
            normalized.append(entry)
    logger.info(f"Loaded {len(normalized)} questions from {input_path}")
    return normalized


# ---------------------------------------------------------------------------
# Local runner (runs through local ADK supervisor)
# ---------------------------------------------------------------------------


def _build_local_supervisor(local_agents: bool = False, direct_agent: bool = False):
    """Build the agent for local load testing.

    Args:
        local_agents: If True, use in-process sub-agents (no Cloud Run
            dependency). If False (default), use the production supervisor
            with RemoteA2aAgent calling deployed Cloud Run A2A services.
        direct_agent: If True, return the policy agent directly (no supervisor).
            This isolates the policy agent's skill/prompt for A/B testing.
    """
    if local_agents or direct_agent:
        from google.adk.agents import Agent
        from google.adk.models import Gemini
        from agents.enterprise.policy_agent.agent import create_agent as create_policy_agent

        model_id = os.getenv("EVAL_MODEL_ID", "gemini-3.5-flash")
        policy_agent = create_policy_agent(model_id=model_id)

        if direct_agent:
            return policy_agent

        # Load supervisor instruction: SKILL.md if skill-evolution, else prompts.py
        prompt_mode = os.getenv("PROMPT_MODE", "skill-evolution").lower()
        if prompt_mode == "skill-evolution":
            from agents.enterprise.policy_agent.skill_loader import load_skill
            supervisor_skill_dir = os.path.join(
                os.path.dirname(__file__),
                "../../enterprise/knowledge_supervisor/app/skill",
            )
            try:
                SUPERVISOR_INSTRUCTION = load_skill(supervisor_skill_dir)
                logger.info("Loaded supervisor SKILL.md from %s", supervisor_skill_dir)
            except FileNotFoundError:
                logger.warning("Supervisor SKILL.md not found, using prompts.py")
                from agents.enterprise.knowledge_supervisor.app.prompts import (
                    SUPERVISOR_INSTRUCTION,
                )
        else:
            from agents.enterprise.knowledge_supervisor.app.prompts import (
                SUPERVISOR_INSTRUCTION,
            )

        from agents.enterprise.hr_calculator.agent import (
            calculate_disability_pay,
            calculate_pto_details,
            calculate_working_days_for_period,
            get_remaining_working_days,
        )

        hr_calculator = Agent(
            name="hr_calculator",
            model=Gemini(model=model_id),
            description=(
                "Calculates PTO balances, sick leave balances, working days for "
                "date ranges, remaining work days in a period, and short-term "
                "disability payouts for a given salary and leave length."
            ),
            instruction=(
                "Calculate PTO balances, working days, and leave details using "
                "your tools. For short-term disability dollar amounts, ALWAYS "
                "use calculate_disability_pay -- never compute pay by hand."
            ),
            tools=[
                calculate_pto_details,
                calculate_working_days_for_period,
                get_remaining_working_days,
                calculate_disability_pay,
            ],
        )

        # Benefits specialist (split out of policy_agent) so the supervisor must
        # disambiguate routing among three agents. Built inline like
        # hr_calculator; its skill is evolvable (registered in agent_registry).
        from agents.enterprise.policy_agent.skill_loader import load_skill
        from agents.enterprise.policy_agent.tools import (
            get_current_date,
            lookup_benefits,
            search_hr_handbook,
        )

        benefits_skill_dir = os.path.join(
            os.path.dirname(__file__),
            "../../enterprise/benefits_agent/skill",
        )
        try:
            benefits_instruction = load_skill(benefits_skill_dir)
        except FileNotFoundError:
            benefits_instruction = "You help employees with questions about company benefits."

        benefits_agent = Agent(
            name="benefits_agent",
            model=Gemini(model=model_id),
            description=(
                "Handles EMPLOYEE BENEFITS questions: health/dental/vision "
                "insurance, HSA, orthodontia, max out-of-pocket, 401k/retirement, "
                "parental and adoption leave, benefits enrollment, the employee "
                "assistance program (EAP), tuition reimbursement, and short-term "
                "disability. Does NOT handle time-off/workplace policies (PTO, "
                "sick leave, remote work, expenses, holidays, bereavement, jury "
                "duty, flex time) -- route those to policy_agent."
            ),
            instruction=benefits_instruction,
            tools=[lookup_benefits, search_hr_handbook, get_current_date],
        )

        # AgentTool (not sub_agents): the supervisor calls each specialist as a
        # tool, gets the result back, and can call MULTIPLE specialists in one
        # turn then synthesize. The handoff/transfer model (sub_agents) cannot do
        # this -- a transfer ends the turn, so compound cross-domain questions
        # (policy + benefits) are unanswerable in a single turn under it.
        from google.adk.tools import AgentTool

        return Agent(
            name="knowledge_supervisor",
            model=Gemini(model=model_id),
            description="A supervisor agent that coordinates other agents.",
            instruction=SUPERVISOR_INSTRUCTION,
            tools=[
                AgentTool(policy_agent),
                AgentTool(benefits_agent),
                AgentTool(hr_calculator),
            ],
        )

    from agents.enterprise.knowledge_supervisor.app.agent import supervisor_agent

    return supervisor_agent


async def _run_one_local(runner, question: str, sem: asyncio.Semaphore) -> dict:
    """Run a single question through local agent and measure metrics."""
    from google.genai import types as genai_types

    async with sem:
        user_id = f"load_{uuid.uuid4().hex[:8]}"
        session_id = f"load_{uuid.uuid4().hex[:8]}"

        start = time.monotonic()
        turn_count = 0
        tool_calls = 0
        errors = 0
        response_text = ""

        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=genai_types.Content(
                    role="user",
                    parts=[genai_types.Part.from_text(text=question)],
                ),
            ):
                if event.author and event.author != "user":
                    turn_count += 1
                if event.content and not event.partial:
                    for part in event.content.parts:
                        if hasattr(part, "function_call") and part.function_call:
                            tool_calls += 1
                        if part.text:
                            response_text = part.text
        except Exception as e:
            errors = 1
            response_text = f"ERROR: {e}"

        latency_ms = (time.monotonic() - start) * 1000

        return {
            "question": question,
            "response": response_text,
            "latency_ms": round(latency_ms, 1),
            "turn_count": turn_count,
            "tool_calls": tool_calls,
            "errors": errors,
            "response_length": len(response_text),
            "session_id": session_id,
        }


def _build_bq_plugins() -> list:
    """Set up BigQuery logging plugins."""
    plugins = []
    dataset_id = os.getenv("DATASET_ID")
    table_id = os.getenv("TABLE_ID")
    dataset_location = os.getenv("DATASET_LOCATION")
    if dataset_id and table_id and dataset_location:
        try:
            from google.adk.plugins.bigquery_agent_analytics_plugin import (
                BigQueryAgentAnalyticsPlugin,
                BigQueryLoggerConfig,
            )

            agent_version = os.getenv("AGENT_VERSION", "unknown")
            # Generator traffic is auto-labeled (traffic_source + a
            # per-invocation run_id) and TRACE_LABELS ("k=v,k2=v2")
            # merges on top — evolution runs can then select exactly
            # this slice with --trace-labels.
            custom_tags = {
                "agent_version": agent_version,
                "traffic_source": "generator",
                "run_id": _RUN_ID,
            }
            for pair in os.getenv("TRACE_LABELS", "").split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    if k.strip():
                        custom_tags[k.strip()] = v.strip()
            logger.info("BQ custom_tags for this run: %s", custom_tags)
            bq_plugin = BigQueryAgentAnalyticsPlugin(
                project_id=PROJECT_ID,
                dataset_id=dataset_id,
                table_id=table_id,
                config=BigQueryLoggerConfig(
                    enabled=True,
                    batch_size=1,
                    shutdown_timeout=10.0,
                    custom_tags=custom_tags,
                ),
                location=dataset_location,
            )
            plugins.append(bq_plugin)
            logger.info(
                "BigQuery logging enabled: %s.%s.%s", PROJECT_ID, dataset_id, table_id
            )
        except Exception as e:
            logger.warning("BigQuery logging not available: %s", e)
    return plugins


def _record_run_labels(session_ids: list) -> None:
    """Persist session->label rows for deployed traffic.

    Deployed agents stamp their BigQuery custom_tags once at startup, so
    per-run labels cannot ride the traces themselves. The generator knows
    the sessions it created, so it records (session_id, label) rows in a
    small side table; label selectors union this with the trace-tag match,
    giving --label identical semantics on the local and deployed paths.
    """
    dataset_id = os.getenv("DATASET_ID")
    if not (dataset_id and session_ids):
        return
    labels = {"run_id": _RUN_ID, "traffic_source": "generator"}
    for pair in os.getenv("TRACE_LABELS", "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            if k.strip():
                labels[k.strip()] = v.strip()
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=PROJECT_ID)
        table = f"{PROJECT_ID}.{dataset_id}.run_labels"
        client.query(
            f"CREATE TABLE IF NOT EXISTS `{table}` ("
            "session_id STRING, label_key STRING, label_value STRING, "
            "run_id STRING, created_at TIMESTAMP)"
        ).result()
        clean = lambda s: str(s).replace("\\", "").replace("'", "")
        rows = ", ".join(
            f"('{clean(sid)}', '{clean(k)}', '{clean(v)}', "
            f"'{_RUN_ID}', CURRENT_TIMESTAMP())"
            for sid in session_ids
            for k, v in labels.items()
        )
        client.query(f"INSERT INTO `{table}` VALUES {rows}").result()
        logger.info(
            "Recorded labels for %d deployed sessions in %s: %s",
            len(session_ids), table, labels,
        )
    except Exception as e:
        logger.warning("run_labels recording failed: %s", e)


async def _send_message(runner, user_id: str, session_id: str, text: str) -> tuple[str, int]:
    """Send a single message and collect the agent's response.

    Returns:
        Tuple of (response_text, tool_call_count).
    """
    from google.genai import types as genai_types

    response_text = ""
    tool_calls = 0
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=text)],
        ),
    ):
        if event.content and not event.partial:
            for part in event.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    tool_calls += 1
                if part.text:
                    response_text = part.text
    return response_text, tool_calls


async def _run_one_multiturn(
    send_fn, sim_client: Client, sim_model: str,
    question: str, sem: asyncio.Semaphore, max_turns: int = 4,
    persona: str = "alex",
    scripted_turns: list | None = None,
    session_factory=None,
) -> dict:
    """Run a multi-turn conversation.

    Follow-up turns come from the user simulator, or — when the question
    carries scripted ``turns`` (e.g. correction-bait pushback) — verbatim
    from the script, in order.

    Args:
        send_fn: async (user_id, session_id, text) -> (response, tool_calls).
        session_factory: optional async () -> (user_id, session_id) for
            targets that issue their own session ids (deployed Agent Engine).
    """
    from agents.workflow.traffic_generator.user_simulator import generate_follow_up

    async with sem:
        if session_factory is not None:
            user_id, session_id = await session_factory()
        else:
            user_id = f"conv_{uuid.uuid4().hex[:8]}"
            session_id = f"conv_{uuid.uuid4().hex[:8]}"

        start = time.monotonic()
        conversation = []  # list of {role, text, tag?}
        total_tool_calls = 0
        corrections = 0
        verifications = 0
        errors = 0

        try:
            # Turn 1: send initial question
            response, tools = await send_fn(user_id, session_id, question)
            total_tool_calls += tools
            conversation.append({"role": "user", "text": question})
            conversation.append({"role": "agent", "text": response})

            if scripted_turns:
                # Scripted follow-ups: send turns[1:] verbatim
                for follow_up in scripted_turns[1:]:
                    conversation.append(
                        {"role": "user", "text": follow_up, "tag": "SCRIPTED"}
                    )
                    response, tools = await send_fn(user_id, session_id, follow_up)
                    total_tool_calls += tools
                    conversation.append({"role": "agent", "text": response})
            else:
                # Subsequent turns: user simulator generates follow-ups
                for turn in range(2, max_turns + 1):
                    tag, follow_up = await generate_follow_up(
                        sim_client, sim_model, conversation, response, turn, persona,
                    )

                    if tag == "END":
                        conversation.append({"role": "user", "text": follow_up, "tag": "END"})
                        break

                    if tag == "CORRECTION":
                        corrections += 1
                    elif tag == "VERIFY":
                        verifications += 1

                    conversation.append({"role": "user", "text": follow_up, "tag": tag})

                    response, tools = await send_fn(user_id, session_id, follow_up)
                    total_tool_calls += tools
                    conversation.append({"role": "agent", "text": response})

        except Exception as e:
            errors = 1
            conversation.append({"role": "system", "text": f"ERROR: {e}"})

        latency_ms = (time.monotonic() - start) * 1000
        user_turns = sum(1 for t in conversation if t["role"] == "user")

        return {
            "question": question,
            "conversation": conversation,
            "user_turns": user_turns,
            "tool_calls": total_tool_calls,
            "corrections": corrections,
            "verifications": verifications,
            "errors": errors,
            "latency_ms": round(latency_ms, 1),
            "session_id": session_id,
            "final_response": next(
                (t["text"] for t in reversed(conversation) if t["role"] == "agent"),
                "",
            ),
        }


async def run_local_multiturn(
    questions: list[dict],
    concurrency: int = 3,
    local_agents: bool = False,
    max_turns: int = 4,
    direct_agent: bool = False,
    persona: str = "alex",
) -> dict:
    """Run multi-turn conversations through local agent with user simulator."""
    from google.adk.apps import App
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    plugins = _build_bq_plugins()
    agent = _build_local_supervisor(
        local_agents=local_agents, direct_agent=direct_agent,
    )
    app = App(root_agent=agent, name="multiturn_test", plugins=plugins)
    session_service = InMemorySessionService()
    runner = Runner(app=app, session_service=session_service, auto_create_session=True)

    async def send_fn(user_id, session_id, text):
        return await _send_message(runner, user_id, session_id, text)

    # Simulator client (separate from agent)
    sim_client = Client(project=PROJECT_ID, location=MODEL_LOCATION)
    sim_model = os.getenv("SIM_MODEL_ID", os.getenv("EVAL_MODEL_ID", "gemini-3.5-flash"))

    sem = asyncio.Semaphore(concurrency)
    total = len(questions)
    logger.info(
        "Running multi-turn: %d conversations, concurrency=%d, max_turns=%d",
        total, concurrency, max_turns,
    )

    start = time.monotonic()
    tasks = [
        _run_one_multiturn(
            send_fn, sim_client, sim_model, q["question"], sem, max_turns, persona,
            scripted_turns=q.get("turns"),
        )
        for q in questions
    ]
    results = list(await asyncio.gather(*tasks))
    results = await _retry_errored(results, questions, lambda q: _run_one_multiturn(
        send_fn, sim_client, sim_model, q["question"], sem, max_turns, persona,
        scripted_turns=q.get("turns"),
    ))
    elapsed = time.monotonic() - start

    return _summarize_multiturn(list(results), total, elapsed, concurrency)


async def _retry_errored(results, questions, make_task):
    """One retry for conversations that died on infrastructure errors
    (quota/503/timeouts). A dead conversation graded as a failure
    silently taxes every quality score; one fresh attempt removes the
    noise without hiding persistent failures."""
    retried = 0
    for i, r in enumerate(results):
        if r.get("errors") and r.get("user_turns", 0) == 0:
            q = questions[i] if i < len(questions) else {"question": r.get("question", "")}
            logger.warning("Retrying dead conversation: %s", r.get("question", "")[:60])
            try:
                results[i] = await make_task(q)
                retried += 1
            except Exception as e:
                logger.warning("Retry failed too: %s", e)
    if retried:
        logger.info("Retried %d dead conversation(s)", retried)
    return results


def _summarize_multiturn(
    results: list, total: int, elapsed: float, concurrency: int,
) -> dict:
    """Print conversation summaries and assemble the multi-turn result dict."""
    total_corrections = 0
    total_verifications = 0
    for r in results:
        total_corrections += r["corrections"]
        total_verifications += r["verifications"]
        tags = [
            t.get("tag", "")
            for t in r["conversation"]
            if t["role"] == "user" and t.get("tag")
        ]
        tag_str = " → ".join(tags) if tags else "single-turn"
        print(f"\n{'='*60}")
        print(f"Q: {r['question']}")
        print(f"   Flow: {tag_str}")
        print(f"   Turns: {r['user_turns']}, Tools: {r['tool_calls']}, "
              f"Corrections: {r['corrections']}, Verifications: {r['verifications']}")
        # Print condensed conversation
        for turn in r["conversation"]:
            role = "👤" if turn["role"] == "user" else "🤖"
            tag = f" [{turn.get('tag', '')}]" if turn.get("tag") else ""
            print(f"   {role}{tag}: {turn['text'][:200]}")

    conversations_with_corrections = sum(
        1 for r in results if r["corrections"] > 0
    )
    conversations_with_verify = sum(
        1 for r in results if r["verifications"] > 0
    )

    metrics = {
        "total_conversations": total,
        "elapsed_seconds": round(elapsed, 1),
        "concurrency": concurrency,
        "total_corrections": total_corrections,
        "total_verifications": total_verifications,
        "correction_rate": round(conversations_with_corrections / total, 3) if total else 0,
        "verify_rate": round(conversations_with_verify / total, 3) if total else 0,
        "avg_user_turns": round(
            sum(r["user_turns"] for r in results) / total, 1
        ) if total else 0,
        "avg_tool_calls": round(
            sum(r["tool_calls"] for r in results) / total, 1
        ) if total else 0,
        "error_count": sum(r["errors"] for r in results),
    }

    return {"metrics": metrics, "conversations": list(results)}


async def run_deployed_multiturn(
    questions: list[dict],
    concurrency: int = 3,
    max_turns: int = 4,
    persona: str = "alex",
) -> dict:
    """Run multi-turn conversations against the deployed Agent Engine supervisor.

    One pass over the question set (scripted turns honored), one Agent Engine
    session per conversation. The deployed agents log to BigQuery themselves
    via their analytics plugin — this runner sends traffic only.
    """
    import vertexai
    from vertexai import agent_engines

    vertexai.init(project=PROJECT_ID, location=REGION)
    display_name = os.getenv("SUPERVISOR_DISPLAY_NAME", "knowledge-supervisor")
    engines = list(agent_engines.list(filter=f'display_name="{display_name}"'))
    if not engines:
        raise RuntimeError(f"Agent Engine '{display_name}' not found")
    engine = engines[0]
    logger.info("Using Agent Engine: %s", engine.resource_name)

    async def _with_quota_retry(fn):
        # Fresh projects default to 90 QueryReasoningEngine requests/min
        # (sessions + streams share it); back off instead of failing the
        # conversation.
        delays = [30, 60, 90, 120]
        for attempt, delay in enumerate([0] + delays):
            if delay:
                logger.warning(
                    "Agent Engine quota exhausted; retrying in %ds (%d/%d)",
                    delay, attempt, len(delays),
                )
                await asyncio.sleep(delay)
            try:
                # Deadline per attempt: a hung engine call otherwise blocks
                # the conversation for ~10 min before surfacing a 503.
                return await asyncio.wait_for(
                    asyncio.to_thread(fn),
                    timeout=float(os.getenv("ENGINE_CALL_TIMEOUT", "120")),
                )
            except asyncio.TimeoutError:
                if attempt == len(delays):
                    raise
            except Exception as e:
                msg = str(e)
                retryable = (
                    "RESOURCE_EXHAUSTED" in msg
                    or "Quota exceeded" in msg
                    or "UNAVAILABLE" in msg
                    or "503" in msg
                )
                if not retryable or attempt == len(delays):
                    raise
        raise RuntimeError("unreachable")

    async def session_factory():
        user_id = f"conv_{uuid.uuid4().hex[:8]}"
        session = await _with_quota_retry(
            lambda: engine.create_session(user_id=user_id)
        )
        session_id = session["id"] if isinstance(session, dict) else session.id
        return user_id, session_id

    async def send_fn(user_id, session_id, text):
        def _call():
            response_text = ""
            tool_calls = 0
            for event in engine.stream_query(
                user_id=user_id, session_id=session_id, message=text,
            ):
                content = event.get("content") if isinstance(event, dict) else None
                for part in (content or {}).get("parts", []):
                    if isinstance(part, dict):
                        if part.get("function_call"):
                            tool_calls += 1
                        if part.get("text"):
                            response_text = part["text"]
            return response_text, tool_calls

        return await _with_quota_retry(_call)

    # Simulator client for unscripted follow-ups
    sim_client = Client(project=PROJECT_ID, location=MODEL_LOCATION)
    sim_model = os.getenv("SIM_MODEL_ID", os.getenv("EVAL_MODEL_ID", "gemini-3.5-flash"))

    sem = asyncio.Semaphore(concurrency)
    total = len(questions)
    logger.info(
        "Running deployed multi-turn: %d conversations, concurrency=%d, max_turns=%d",
        total, concurrency, max_turns,
    )

    start = time.monotonic()
    tasks = [
        _run_one_multiturn(
            send_fn, sim_client, sim_model, q["question"], sem, max_turns, persona,
            scripted_turns=q.get("turns"),
            session_factory=session_factory,
        )
        for q in questions
    ]
    results = list(await asyncio.gather(*tasks))
    results = await _retry_errored(results, questions, lambda q: _run_one_multiturn(
        send_fn, sim_client, sim_model, q["question"], sem, max_turns, persona,
        scripted_turns=q.get("turns"),
        session_factory=session_factory,
    ))
    elapsed = time.monotonic() - start

    return _summarize_multiturn(list(results), total, elapsed, concurrency)


async def run_local(
    questions: list[dict], concurrency: int = 5, local_agents: bool = False
) -> dict:
    """Run all questions through local agent and aggregate metrics."""
    from google.adk.apps import App
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    plugins = _build_bq_plugins()

    supervisor = _build_local_supervisor(local_agents=local_agents)
    app = App(root_agent=supervisor, name="load_test", plugins=plugins)
    session_service = InMemorySessionService()
    runner = Runner(app=app, session_service=session_service, auto_create_session=True)

    sem = asyncio.Semaphore(concurrency)
    total = len(questions)
    logger.info("Running locally: %d questions, concurrency=%d", total, concurrency)

    start = time.monotonic()
    tasks = [_run_one_local(runner, q["question"], sem) for q in questions]
    results = await asyncio.gather(*tasks)
    elapsed = time.monotonic() - start

    # Print per-session results
    for r in results:
        print(f"\nQ: {r['question']}")
        print(f"A: {r['response'][:300]}")
        print(f"   (turns: {r['turn_count']}, tools: {r['tool_calls']}, "
              f"latency: {r['latency_ms']:.0f}ms)")

    # Aggregate metrics
    latencies = [r["latency_ms"] for r in results]
    turns = [r["turn_count"] for r in results]
    tool_call_counts = [r["tool_calls"] for r in results]
    error_count = sum(r["errors"] for r in results)

    metrics = {
        "total_queries": total,
        "elapsed_seconds": round(elapsed, 1),
        "concurrency": concurrency,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "p50_latency_ms": round(sorted(latencies)[len(latencies) // 2], 1)
        if latencies
        else 0,
        "p95_latency_ms": round(sorted(latencies)[int(len(latencies) * 0.95)], 1)
        if latencies
        else 0,
        "max_latency_ms": round(max(latencies), 1) if latencies else 0,
        "avg_turns": round(sum(turns) / len(turns), 1) if turns else 0,
        "avg_tool_calls": round(sum(tool_call_counts) / len(tool_call_counts), 1)
        if tool_call_counts
        else 0,
        "error_count": error_count,
        "error_rate": round(error_count / total, 3) if total else 0,
        "throughput_qps": round(total / elapsed, 2) if elapsed else 0,
    }

    return {"metrics": metrics, "sessions": list(results)}


# ---------------------------------------------------------------------------
# Deployed runner (sends to Reasoning Engine)
# ---------------------------------------------------------------------------

shutdown_requested = False


def handle_sigterm(signum, frame):
    global shutdown_requested
    logger.info(
        "Received SIGTERM -- finishing current batch and shutting down gracefully..."
    )
    shutdown_requested = True


# Only the main thread may install signal handlers. This module is also
# imported from analyst worker threads (evolve._derive_toolbox), where
# signal.signal() raises ValueError.
if threading.current_thread() is threading.main_thread():
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)


async def run_deployed(
    questions: list[dict],
    concurrency: int,
    duration_minutes: float,
) -> None:
    """Send questions to the deployed Reasoning Engine in batches."""
    global shutdown_requested

    import vertexai
    from vertexai import agent_engines

    vertexai.init(project=PROJECT_ID, location=REGION)

    display_name = os.getenv("SUPERVISOR_DISPLAY_NAME", "knowledge-supervisor")
    logger.info(f"Searching for Agent Engine '{display_name}'...")
    engines = list(agent_engines.list(filter=f'display_name="{display_name}"'))
    if not engines:
        logger.error(f"ERROR: Agent Engine '{display_name}' not found!")
        return
    engine = engines[0]
    logger.info(f"Using Agent Engine: {engine.resource_name}")

    sem = asyncio.Semaphore(concurrency)
    start_time = time.time()
    max_duration_seconds = duration_minutes * 60
    query_count = 0
    question_texts = [q["question"] for q in questions]

    async def run_single_query(q):
        nonlocal query_count
        async with sem:
            current_query_num = query_count + 1
            query_count += 1
            logger.info(f"[Query {current_query_num}] Sending: {q}")

            start_query_time = time.time()
            try:
                # AdkApp deployments register stream_query (a plain `query`
                # class_method does not exist), so stream and keep the last
                # text part as the answer.
                def _call():
                    text = ""
                    for event in engine.stream_query(
                        user_id=f"load_{uuid.uuid4().hex[:8]}", message=q,
                    ):
                        content = (
                            event.get("content") if isinstance(event, dict) else None
                        )
                        for part in (content or {}).get("parts", []):
                            if isinstance(part, dict) and part.get("text"):
                                text = part["text"]
                    return text

                final_answer = await asyncio.to_thread(_call)
            except Exception as e:
                logger.info(f"[Query {current_query_num}] Error: {e}")
                final_answer = f"Error: {e}"

            latency = time.time() - start_query_time
            logger.info(
                f"[Query {current_query_num}] Finished in {latency:.2f}s. "
                f"Answer: {final_answer}"
            )

    logger.info(f"Starting load test for {duration_minutes} minutes...")

    while time.time() - start_time < max_duration_seconds and not shutdown_requested:
        logger.info(f"\n--- Batch of {len(question_texts)} queries ---")
        tasks = [run_single_query(q) for q in question_texts]
        await asyncio.gather(*tasks)

        if shutdown_requested:
            logger.info("Shutdown requested -- stopping after current batch.")
            break
        if time.time() - start_time >= max_duration_seconds:
            break
        logger.info("\nBatch completed. Repeating...")

    elapsed = time.time() - start_time
    logger.info(
        f"\nLoad test completed. {query_count} queries in {elapsed / 60:.1f} minutes"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_multiturn_metrics(metrics: dict):
    """Print multi-turn conversation results summary."""
    print("\n" + "=" * 60)
    print("  MULTI-TURN CONVERSATION RESULTS")
    print("=" * 60)
    print(f"  Conversations:     {metrics['total_conversations']}")
    print(f"  Duration:          {metrics['elapsed_seconds']}s")
    print(f"  Avg user turns:    {metrics['avg_user_turns']}")
    print(f"  Avg tool calls:    {metrics['avg_tool_calls']}")
    print(f"  Corrections:       {metrics['total_corrections']} "
          f"({metrics['correction_rate']*100:.1f}% of conversations)")
    print(f"  Verifications:     {metrics['total_verifications']} "
          f"({metrics['verify_rate']*100:.1f}% of conversations)")
    print(f"  Errors:            {metrics['error_count']}")
    print("=" * 60)


def _print_metrics(metrics: dict):
    """Print load test results summary."""
    print("\n" + "=" * 60)
    print("  LOAD TEST RESULTS")
    print("=" * 60)
    print(f"  Queries:        {metrics['total_queries']}")
    print(f"  Duration:       {metrics['elapsed_seconds']}s")
    print(f"  Throughput:     {metrics['throughput_qps']} qps")
    print(f"  Avg latency:    {metrics['avg_latency_ms']}ms")
    print(f"  P50 latency:    {metrics['p50_latency_ms']}ms")
    print(f"  P95 latency:    {metrics['p95_latency_ms']}ms")
    print(f"  Max latency:    {metrics['max_latency_ms']}ms")
    print(f"  Avg turns:      {metrics['avg_turns']}")
    print(f"  Avg tool calls: {metrics['avg_tool_calls']}")
    print(
        f"  Errors:         {metrics['error_count']} ({metrics['error_rate']*100:.1f}%)"
    )
    print("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic traffic and run against the knowledge supervisor."
    )
    # Generation
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Generate COUNT questions across default topics.",
    )
    parser.add_argument(
        "--topics",
        type=str,
        default=None,
        help="Topics config as 'topic:count,topic:count'. Overrides TOPICS_CONFIG env var.",
    )
    parser.add_argument(
        "-q",
        "--question",
        type=str,
        default=None,
        help="Run a single question directly (no generation).",
    )
    parser.add_argument(
        "--from-file",
        type=str,
        default=None,
        help="Load questions from this JSON file instead of generating.",
    )
    parser.add_argument(
        "--generate-only",
        action="store_true",
        help="Generate questions only, don't run them.",
    )
    parser.add_argument(
        "--no-out-of-scope",
        action="store_true",
        help="Don't generate out-of-scope questions from agent_context.json.",
    )
    parser.add_argument(
        "--eval-format",
        action="store_true",
        help="Output in eval_cases format (deduplicates against golden eval set).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Save generated questions to this JSON file.",
    )
    # Execution
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Run only the first N questions of --from-file (exact "
        "session count for demos).",
    )
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        metavar="K=V",
        help="Custom label stamped into every BQ event of this run "
        "(repeatable, e.g. --label experiment=round1). Labels reach "
        "BigQuery on the --local path (deployed agents' plugins fix "
        "their tags at startup); evolve on the slice with the job's "
        "--trace-labels.",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Run through local ADK supervisor. Uses production A2A agents by default.",
    )
    parser.add_argument(
        "--local-agents",
        action="store_true",
        help="With --local: use in-process sub-agents instead of Cloud Run A2A. "
        "Faster, no auth needed, but no A2A events in traces.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Number of concurrent requests (default: 5 local, 3 deployed).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Deployed mode: test duration in minutes (default: 5).",
    )
    parser.add_argument(
        "--multi-turn",
        action="store_true",
        help="Run multi-turn conversations with user simulator follow-ups.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=4,
        help="Maximum user turns per conversation in multi-turn mode (default: 4).",
    )
    parser.add_argument(
        "--persona",
        type=str,
        choices=["alex", "morgan"],
        default="alex",
        help="Simulator persona: alex (core topics) or morgan (all + field knowledge).",
    )
    parser.add_argument(
        "--direct-agent",
        action="store_true",
        help="Run directly against policy_agent (no supervisor). Isolates skill/prompt effect.",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    if getattr(args, "label", None):
        extra = ",".join(args.label)
        base = os.getenv("TRACE_LABELS", "")
        os.environ["TRACE_LABELS"] = f"{base},{extra}" if base else extra
        logger.info(
            "Custom labels for this run: %s (run_id=%s)", extra, _RUN_ID,
        )
        if not args.local:
            logger.info(
                "Deployed run: labels are recorded in the run_labels side "
                "table when the run completes (deployed traces carry "
                "startup-fixed tags only)."
            )

    # --- Step 1: Get questions ---
    if args.question:
        questions = [{"question": args.question, "topic": "manual"}]
    elif args.from_file:
        questions = load_questions(args.from_file)
        if getattr(args, "limit", None):
            questions = questions[: args.limit]
            logger.info(
                "Limited to first %d question(s) of %s",
                len(questions), args.from_file,
            )
    else:
        # Resolve topics config
        if args.count:
            topics_str = _topics_from_count(args.count)
        else:
            topics_str = args.topics or os.getenv(
                "TOPICS_CONFIG", "pto:5,benefits:5,expenses:5,holidays:5"
            )
        topics_config = parse_topics_config(topics_str)

        logger.info("--- Configuration ---")
        logger.info(f"Topics:   {topics_str}")
        logger.info("---------------------")

        questions = await generate_all_questions(
            topics_config, include_out_of_scope=not args.no_out_of_scope
        )

        # Append Morgan's field knowledge questions when using that persona
        if args.persona == "morgan":
            morgan_path = os.path.join(
                os.path.dirname(__file__),
                "../../../eval/data/questions/morgan_field_knowledge.json",
            )
            if os.path.isfile(morgan_path):
                with open(morgan_path) as f:
                    morgan_qs = json.load(f).get("questions", [])
                questions.extend(morgan_qs)
                logger.info("Added %d Morgan field knowledge questions", len(morgan_qs))

        logger.info(f"Generated {len(questions)} questions:")
        for i, q in enumerate(questions, 1):
            logger.info(f"  {i}. [{q['topic']}] {q['question']}")

    # --- Step 2: Save questions to file (only for generate-only mode) ---
    # Don't pre-write to --output when we'll run conversations, because if the
    # run is interrupted the output file will contain raw questions instead of
    # results -- a silent data-loss bug.
    if args.output and args.generate_only:
        save_questions(questions, args.output, eval_format=args.eval_format)

    # --- Step 3: Run or exit ---
    if args.generate_only:
        if not args.output:
            if args.eval_format:
                print(json.dumps(_to_eval_format(questions), indent=2))
            else:
                print(json.dumps({"questions": questions}, indent=2))
        return

    if args.local:
        concurrency = args.concurrency or 5

        if args.multi_turn:
            # Multi-turn conversations with user simulator
            result = await run_local_multiturn(
                questions,
                concurrency=concurrency,
                local_agents=args.local_agents,
                max_turns=args.max_turns,
                direct_agent=args.direct_agent,
                persona=args.persona,
            )
            _print_multiturn_metrics(result["metrics"])
        else:
            # Single-turn Q&A
            result = await run_local(
                questions, concurrency=concurrency, local_agents=args.local_agents
            )
            _print_metrics(result["metrics"])

        # Save results
        output_path = args.output or os.path.join(
            os.path.dirname(__file__), "../../../eval/load_test_results.json"
        )
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        logger.info("Results saved to %s", output_path)

    else:
        # Run against deployed Reasoning Engine
        concurrency = args.concurrency or int(os.getenv("CONCURRENCY", "3"))
        if args.multi_turn or args.from_file:
            # One pass over the question set, one Agent Engine session per
            # conversation. --from-file without --multi-turn seeds each
            # question as a single turn (max_turns=1 skips the simulator);
            # the duration-based load loop below is reserved for generated
            # topic traffic.
            result = await run_deployed_multiturn(
                questions,
                concurrency=concurrency,
                max_turns=args.max_turns if args.multi_turn else 1,
                persona=args.persona,
            )
            _print_multiturn_metrics(result["metrics"])
            if os.getenv("TRACE_LABELS"):
                _record_run_labels([
                    c.get("session_id")
                    for c in result.get("conversations", [])
                    if c.get("session_id")
                ])
            output_path = args.output or os.path.join(
                os.path.dirname(__file__), "../../../eval/load_test_results.json"
            )
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "w") as f:
                json.dump(result, f, indent=2, default=str)
            logger.info("Results saved to %s", output_path)
        else:
            duration_minutes = args.duration or float(os.getenv("DURATION_MINUTES", "5"))
            await run_deployed(questions, concurrency, duration_minutes)

    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
