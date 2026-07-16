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

"""User simulator for multi-turn conversation testing.

Plays the role of a skeptical employee who knows the actual policy data
from onboarding materials. Detects hallucination, pushes back on vague
answers, and asks natural follow-ups.
"""

import json
import logging
import os
import re
from enum import Enum

from google.genai import Client
from google.genai import types
from pydantic import BaseModel


class SimulatorTag(str, Enum):
    CORRECTION = "CORRECTION"
    VERIFY = "VERIFY"
    SPECIFICS = "SPECIFICS"
    SCOPE = "SCOPE"
    FOLLOWUP = "FOLLOWUP"
    END = "END"


class SimulatorResponse(BaseModel):
    tag: SimulatorTag
    message: str

logger = logging.getLogger("user_simulator")

PERSONAS = {
    "alex": {
        "name": "Alex",
        "role": "new employee who recently completed onboarding",
        "known_topics": [
            "pto", "sick_leave", "remote_work", "holidays", "out_of_scope",
        ],
        "extra_knowledge": None,
    },
    "morgan": {
        "name": "Morgan",
        "role": "senior employee and former HR compliance specialist",
        "known_topics": None,
        "extra_knowledge": {
            "tuition_reimbursement": (
                "TUITION REIMBURSEMENT: $5,000/year for accredited degree programs, "
                "requires manager + HR approval, must maintain B+ average, "
                "1-year employment commitment post-completion, submit through learning.company.com."
            ),
            "bereavement_leave": (
                "BEREAVEMENT LEAVE: 5 days paid for immediate family (spouse, parent, child, sibling), "
                "3 days for extended family (grandparent, in-law, aunt/uncle), "
                "additional unpaid leave with manager approval."
            ),
            "jury_duty": (
                "JURY DUTY: Full pay for up to 10 days/year, must provide jury summons copy, "
                "return to work same day if dismissed before noon."
            ),
            "employee_assistance": (
                "EMPLOYEE ASSISTANCE PROGRAM (EAP): 6 free confidential counseling sessions/year, "
                "24/7 crisis line, 1 hour free legal consultation, financial planning, "
                "available to employee + household members."
            ),
        },
    },
}

_POLICY_REFERENCE_CACHE: dict[str, str] = {}


def _build_policy_reference(persona_id: str) -> str:
    """Build POLICY_REFERENCE dynamically from golden_evals.json for a persona."""
    if persona_id in _POLICY_REFERENCE_CACHE:
        return _POLICY_REFERENCE_CACHE[persona_id]

    if persona_id not in PERSONAS:
        raise ValueError(f"Unknown persona: {persona_id}. Valid: {list(PERSONAS.keys())}")

    persona = PERSONAS[persona_id]
    known_topics = persona["known_topics"]

    golden_path = os.path.join(
        os.path.dirname(__file__), "../../../eval/data/golden_evals.json",
    )
    with open(golden_path) as f:
        golden_data = json.load(f)

    cases = golden_data["eval_cases"]
    if known_topics is not None:
        cases = [c for c in cases if c.get("topic") in known_topics]

    by_topic: dict[str, list[dict]] = {}
    for c in cases:
        by_topic.setdefault(c["topic"], []).append(c)

    lines = [
        "You memorized these facts from your onboarding packet. "
        "If the bot contradicts ANY of them, you MUST push back.\n",
    ]

    ordered = sorted(t for t in by_topic if t != "out_of_scope")
    if "out_of_scope" in by_topic:
        ordered.append("out_of_scope")

    for topic in ordered:
        entries = by_topic[topic]
        label = topic.upper().replace("_", " ")

        if topic == "out_of_scope":
            subjects = []
            for e in entries:
                q = e["question"].lower().rstrip("?").strip()
                for prefix in ("what are the ", "how do i ", "can you help me ", "what's the "):
                    if q.startswith(prefix):
                        q = q[len(prefix):]
                        break
                subjects.append(q)
            lines.append(f"OUT OF SCOPE (bot should NOT answer): {', '.join(subjects)}.")
            continue

        facts = []
        for e in entries:
            answer = e.get("expected_answer", "")
            if answer.startswith("DECLINE"):
                continue
            facts.append(answer)

        if facts:
            lines.append(f"{label}: {' '.join(facts)}")

    if persona["extra_knowledge"]:
        lines.append("\nADDITIONAL KNOWLEDGE from your previous HR experience:")
        for text in persona["extra_knowledge"].values():
            lines.append(text)

    reference = "\n".join(lines)
    _POLICY_REFERENCE_CACHE[persona_id] = reference
    logger.debug(
        "Built POLICY_REFERENCE for %s: %d topics, %d chars",
        persona_id, len(by_topic), len(reference),
    )
    return reference

SIMULATOR_PROMPT = """\
You are {persona_name}, a {persona_role}, chatting with the company HR bot. You know the facts below.

{policy_reference}

CONVERSATION:
{conversation_history}
BOT: {agent_response}

INSTRUCTIONS: Compare the bot's latest reply against your known facts. Pick a tag and write a complete reply as {persona_name}.

Tag meanings (pick the first that applies):
- CORRECTION: The bot stated something WRONG (wrong number, wrong policy, claimed a non-existent holiday). Quote the error and state the correct fact.
- VERIFY: The bot's answer sounds generic or not based on actual policy lookup. Ask it to check the real policy.
- SPECIFICS: The bot was vague (no numbers, dates, or limits). Ask for the exact figure.
- SCOPE: The bot answered a question about salary, IT, promotions, dress code, or training. Point out it shouldn't answer that.
- FOLLOWUP: The answer was correct and specific. Ask about a related topic.
- END: The answer was correct and specific, and you're satisfied. Say thanks.

CRITICAL RULES:
- If the bot says "X IS a company holiday" but X is NOT in your holiday list, that is WRONG — use CORRECTION.
- If the bot correctly says "X is NOT a company holiday" and X is indeed not in your list, that is CORRECT — use END or FOLLOWUP.
- If the bot says a wrong number (e.g., "6% match" when you know it's 4%), use CORRECTION.
- If the bot says sick days roll over, use CORRECTION.
- If the bot mentions more than 3 remote work days, use CORRECTION.
- Only use END or FOLLOWUP if the bot's answer is factually accurate AND includes specific numbers/details.
- Read the bot's answer carefully. "Not listed" or "is not" means the bot is DENYING, not claiming. Only correct actual errors.
- Always write a COMPLETE sentence that ends with proper punctuation (. ? !). Never stop mid-sentence.
"""


def _compact_response(text: str, max_len: int = 300) -> str:
    """Compact a verbose agent response into key facts.

    Extracts sentences containing specific policy data (numbers, dates,
    percentages, dollar amounts) and drops filler/pleasantries. This is
    a fast, non-LLM approach that preserves all factual claims the
    simulator needs to verify.
    """
    if len(text) <= max_len:
        return text

    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    # Patterns that indicate factual content worth keeping
    fact_patterns = re.compile(
        r'\d+|%|\$|days?/|per year|per month|weeks?|hours?|match'
        r'|not\b|no\b|cannot|don.t|isn.t|aren.t|doesn.t'
        r'|holiday|pto|sick|remote|expense|benefit|dental|vision|401'
        r'|parental|rollover|accrual|approval|receipt|core hours'
        r'|out.of.scope|cannot assist|unable',
        re.IGNORECASE,
    )
    # Patterns for filler we can drop
    filler_patterns = re.compile(
        r'^(sure|of course|great question|i\'d be happy|let me|'
        r'is there anything else|feel free|don\'t hesitate|happy to help'
        r'|hope this|glad to|thank you for|you\'re welcome)',
        re.IGNORECASE,
    )

    kept = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if filler_patterns.search(s):
            continue
        if fact_patterns.search(s):
            kept.append(s)

    if not kept:
        # Fallback: keep first and last sentence
        kept = [sentences[0].strip()]
        if len(sentences) > 1:
            kept.append(sentences[-1].strip())

    result = " ".join(kept)
    # If still too long, keep only the most fact-dense sentences
    if len(result) > max_len * 2:
        scored = sorted(
            kept,
            key=lambda s: len(fact_patterns.findall(s)),
            reverse=True,
        )
        result = " ".join(scored[: max(3, len(scored) // 2)])

    return result


async def generate_follow_up(
    client: Client,
    model_id: str,
    conversation_history: list[dict],
    agent_response: str,
    turn_number: int,
    persona: str = "alex",
) -> tuple[str, str]:
    """Generate a follow-up message from the simulated user.

    Args:
        client: Gemini client
        model_id: Model to use for generation
        conversation_history: List of {"role": "user"|"agent", "text": ...}
        agent_response: The agent's last response
        turn_number: Current turn number (1-indexed)
        persona: Persona ID ("alex" or "morgan")

    Returns:
        Tuple of (tag, message). Tag is one of: CORRECTION, VERIFY,
        SPECIFICS, SCOPE, FOLLOWUP, END.
    """
    # Format conversation history — compact verbose agent responses to
    # preserve key facts while keeping the prompt short enough for the
    # model to generate complete follow-ups.
    persona_config = PERSONAS.get(persona, PERSONAS["alex"])
    history_text = ""
    for turn in conversation_history:
        role = f"You ({persona_config['name']})" if turn["role"] == "user" else "HR Bot"
        text = turn["text"]
        # Compact agent responses: extract key facts, drop filler
        if turn["role"] == "agent":
            text = _compact_response(text, max_len=300)
        history_text += f"{role}: {text}\n\n"

    # Compact the current agent response for the simulator
    compacted_response = _compact_response(agent_response, max_len=500)

    prompt = SIMULATOR_PROMPT.format(
        persona_name=persona_config["name"],
        persona_role=persona_config["role"],
        policy_reference=_build_policy_reference(persona),
        conversation_history=history_text.strip() or "(This is the start of the conversation)",
        agent_response=compacted_response,
    )

    # Bias toward ending in later turns
    if turn_number >= 4:
        prompt += "\n\nIMPORTANT: This conversation has gone on long enough. Strongly prefer ending with END unless the bot said something clearly wrong."
    elif turn_number >= 3:
        prompt += "\n\nNote: Consider wrapping up unless there's something important to follow up on."

    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            # Higher temperature for follow-up turns to avoid repetitive short responses
            temp = 0.4 if turn_number <= 2 else 0.5
            response = client.models.generate_content(
                model=model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SimulatorResponse,
                    temperature=temp,
                    max_output_tokens=1000,
                ),
            )
            raw = response.text.strip()

            data = json.loads(raw)
            tag = data.get("tag", "FOLLOWUP")
            text = data.get("message", "").strip()

            if not text or len(text) < 5:
                return "END", "Thanks, that helps!"

            # Retry if the message ends mid-sentence (no terminal punctuation)
            if attempt < max_attempts - 1 and not re.search(r'[.?!]$', text):
                logger.info(
                    "Simulator output truncated (attempt %d), retrying: %s",
                    attempt + 1, text[:60],
                )
                continue

            valid_tags = {t.value for t in SimulatorTag}
            if tag not in valid_tags:
                tag = "FOLLOWUP"

            logger.info("Simulator [%s]: %s", tag, text[:80])
            return tag, text

        except Exception as e:
            logger.warning("User simulator error (attempt %d): %s", attempt + 1, e)

    return "END", "Thanks, that helps!"
