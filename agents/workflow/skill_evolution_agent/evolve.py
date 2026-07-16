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

"""Skill Evolution Pipeline.

Analyzes execution trajectories from a quality report and evolves an
agent's SKILL.md through parallel analyst fleet + patch consolidation.

Based on:
- Trace2Skill (arXiv:2603.25158): parallel analyst fleet + hierarchical
  patch consolidation
- AutoSkill (arXiv:2603.01145): online skill extraction + versioned merging

Library module — invoked via tools.py (ADK agent) or main.py (CLI).
"""

import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from google.genai import types

# Allow running from project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, PROJECT_ROOT)

from agents.workflow.skill_evolution_agent.prompts import (
    COMPACTION_PROMPT,
    CONSOLIDATOR_PROMPT,
    ERROR_ANALYST_PROMPT,
    HIERARCHICAL_CONSOLIDATOR_PROMPT,
    SUCCESS_ANALYST_PROMPT,
)

logger = logging.getLogger(__name__)


def _record_evolved_score(candidates_dir: str | None, score: float | None) -> None:
    """Persist the deployed skill's authoritative selection score.

    Written to ``<run_dir>/evolved_score.json`` so ``compare_versions`` reports
    the same score the incumbent-guarded selection used, rather than re-scoring
    versions on separate (noisy) traffic. Last writer wins, which is correct:
    in sequential co-evolution the final agent is scored against the others'
    already-deployed winners, so it reflects the full evolved system.
    """
    if not candidates_dir or score is None:
        return
    try:
        run_dir = os.path.dirname(candidates_dir.rstrip("/"))
        with open(os.path.join(run_dir, "evolved_score.json"), "w") as f:
            json.dump({"version": "evolved", "meaningful_rate": score}, f)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not record evolved score: %s", e)


def load_current_skill(skill_dir: str) -> str:
    """Read the full SKILL.md content from the skill directory."""
    skill_path = os.path.join(skill_dir, "SKILL.md")
    with open(skill_path) as f:
        return f.read()


def _has_parroted_recovery(session: dict) -> bool:
    """Check if session has a parroted sub-trajectory outcome."""
    for st in session.get("sub_trajectories", []):
        if st.get("outcome") == "parroted":
            return True
    for st in session.get("execution_sub_trajectories", []):
        if st.get("outcome") == "parroted":
            return True
    return False


def partition_trajectories(report: dict) -> tuple[list, list]:
    """Split sessions into successes (T+) and failures (T-).

    Sessions scored "meaningful" but containing parroted recoveries
    are reclassified as T- — the agent didn't genuinely recover,
    the user did the agent's work.
    """
    sessions = report.get("sessions", [])
    successes = []
    failures = []
    for s in sessions:
        usefulness = (
            s.get("metrics", {})
            .get("response_usefulness", {})
            .get("category", "")
        )
        if usefulness in ("meaningful", "declined"):
            if _has_parroted_recovery(s):
                failures.append(s)
            else:
                successes.append(s)
        elif usefulness in ("unhelpful", "partial"):
            failures.append(s)
    return successes, failures


def _format_conversation(conversation) -> str:
    """Format a conversation into readable text.

    Accepts either a list of turn dicts (from traffic generator / quality
    report JSON) or a pre-formatted string (legacy).  Returns a readable
    string or "" if there is nothing to format.
    """
    if isinstance(conversation, str):
        return conversation
    if not isinstance(conversation, list) or not conversation:
        return ""
    parts = []
    for turn in conversation:
        role = (turn.get("role") or "?").capitalize()
        text = turn.get("text", "")
        tag = turn.get("tag") or turn.get("inferred_tag") or ""
        tag_str = f" [{tag}]" if tag else ""
        parts.append(f"{role}{tag_str}: {text}")
    return "\n".join(parts)


def format_trajectory(session: dict) -> str:
    """Format a session dict for analyst consumption.

    Handles both single-turn (question/response) and multi-turn
    (conversation list with user corrections) formats.
    """
    metrics = session.get("metrics", {})
    usefulness = metrics.get("response_usefulness", {})
    grounding = metrics.get("task_grounding", {})

    # Use full conversation if available (multi-turn)
    conversation = _format_conversation(session.get("conversation", []))
    if conversation:
        # Include correction/verification counts for context
        corrections = session.get("corrections", 0)
        verifications = session.get("verifications", 0)
        quality = session.get("quality_scores", {})

        result = f"=== Conversation ===\n{conversation}\n\n"
        result += f"Agent: {session.get('answered_by', '')}\n"
        result += f"Verdict: {usefulness.get('category', '')}\n"
        result += f"Justification: {usefulness.get('justification', '')}\n"
        result += f"Grounding: {grounding.get('category', '')}\n"
        if corrections:
            result += f"User corrections: {corrections}\n"
        if verifications:
            result += f"User verification requests: {verifications}\n"
        # Include dimension scores if available
        for dim in ("correctness", "tool_usage", "specificity",
                     "scope_compliance", "first_time_right"):
            score_data = quality.get(dim, {})
            if score_data:
                result += f"{dim}: {score_data.get('score', '?')}/2 - {score_data.get('reason', '')}\n"

        boundaries = session.get("correction_boundaries", [])
        if boundaries:
            result += "\n=== Correction Evidence ===\n"
            for b in boundaries:
                result += f"Turn {b.get('turn_index')}: "
                result += f"Agent claimed: \"{b.get('wrong_claim', '')}\"\n"
                result += f"  User corrected: \"{b.get('correct_fact', '')}\"\n"
                result += f"  Agent recovered: {b.get('agent_recovered', False)}\n"

        exec_sub_trajs = session.get("execution_sub_trajectories", [])
        if exec_sub_trajs:
            result += "\n=== Execution Sub-Trajectories ===\n"
            result += "Each segment shows agent routing/tool calls for that part of the conversation.\n"
            result += "Compare [-] (wrong) vs [+] (recovered) vs [~] (parroted) segments.\n\n"
            for seg in exec_sub_trajs:
                outcome = seg.get("outcome", "")
                if outcome == "recovered":
                    icon = "+"
                elif outcome == "parroted":
                    icon = "~"
                else:
                    icon = "-"
                result += f"--- [{icon}] {seg.get('label')} "
                result += f"(turns {seg.get('start_turn')}-{seg.get('end_turn')}) "
                result += f"-> {seg.get('outcome')} ---\n"
                result += seg.get("trace", "") + "\n\n"
        else:
            sub_trajs = session.get("sub_trajectories", [])
            if sub_trajs:
                result += "\n=== Sub-Trajectories ===\n"
                for st in sub_trajs:
                    result += f"{st.get('label')}: turns {st.get('start_turn')}-{st.get('end_turn')} -> {st.get('outcome')}\n"

            exec_trace = session.get("execution_trace", "")
            if exec_trace:
                result += "\n=== Execution Trace ===\n"
                result += "Shows agent routing, tool calls, and LLM requests.\n"
                result += "Look for: missing tool calls, wrong routing, tool errors.\n\n"
                result += exec_trace + "\n"

        return result

    # Fallback: single-turn format
    return (
        f"Question: {session.get('question', '')}\n"
        f"Response: {session.get('response', '')}\n"
        f"Agent: {session.get('answered_by', '')}\n"
        f"Verdict: {usefulness.get('category', '')}\n"
        f"Justification: {usefulness.get('justification', '')}\n"
        f"Grounding: {grounding.get('category', '')}"
    )


def run_analyst(
    client: genai.Client,
    model_id: str,
    system_prompt: str,
    session: dict,
    current_skill: str,
) -> str | None:
    """Run a single analyst on one trajectory. Returns patch text or None."""
    trajectory = format_trajectory(session)
    prompt = (
        f"<current_skill>\n{current_skill}\n</current_skill>\n\n"
        f"<trajectory>\n{trajectory}\n</trajectory>\n\n"
        f"Analyze this trajectory and propose your patch."
    )
    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.3,
        ),
    )
    text = response.text.strip()
    if "NO_PATCH" in text and len(text) < 200:
        return None
    return text


ROOT_CAUSE_CATEGORIES = {
    "KEYWORD_GAP", "MISSING_RULE", "AMBIGUITY", "SCOPE_GAP", "HALLUCINATION",
    "CORRECTION_IGNORE",
    "KEYWORD_MAPPING", "RESPONSE_PATTERN", "DISAMBIGUATION", "TOOL_USAGE",
    "CORRECTION_RECOVERY",
}


def passes_quality_gate(patch: str) -> bool:
    """Reject patches that lack structure or root cause categorization.

    Per Trace2Skill: analysts must provide a verified causal chain.
    We check for structured headings and actionable content.
    """
    if len(patch.strip()) < 50:
        return False
    if not any(cat in patch for cat in ROOT_CAUSE_CATEGORIES):
        return False
    has_analysis = ("## Root Cause" in patch or "## Pattern" in patch)
    has_patch = ("## Proposed Patch" in patch or "Content:" in patch)
    if not (has_analysis and has_patch):
        return False
    return True


def strip_code_fences(text: str) -> str:
    """Strip markdown code fences if the model wrapped the output."""
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        stripped = "\n".join(lines).strip()
        # If stripping fences produced empty content, return original
        if not stripped:
            logger.warning("strip_code_fences produced empty result, returning original text")
            return text
        return stripped
    return text


_ADK_VAR_RE = re.compile(r"\{(\w+)\}")

_ADK_KNOWN_VARS = frozenset()


def sanitize_adk_vars(skill: str) -> str:
    """Escape {identifier} patterns that ADK would interpret as context vars.

    ADK's instructions_utils resolves any {valid_python_identifier} in
    SKILL.md as a session state variable, crashing with KeyError when the
    variable doesn't exist. Evolved skills often contain template-like
    references (e.g. {requested_topic}) from tool error messages that
    must be escaped.

    Replaces {word} with <word> unless the identifier is a known ADK
    state variable.
    """
    def _replace(m: re.Match) -> str:
        name = m.group(1)
        if name in _ADK_KNOWN_VARS:
            return m.group(0)
        return f"<{name}>"

    return _ADK_VAR_RE.sub(_replace, skill)


def validate_evolved_skill(evolved: str, current_skill: str) -> list[str]:
    """Check evolved skill for structural issues (Trace2Skill guardrails).

    Returns list of issue descriptions. Empty list = valid.
    """
    issues = []

    if "---" not in evolved:
        issues.append("Missing YAML frontmatter")
    else:
        import re
        fm_match = re.match(r"---\n(.*?)\n---", evolved, re.DOTALL)
        if fm_match:
            try:
                import yaml
                yaml.safe_load(fm_match.group(1))
            except Exception as e:
                issues.append(f"Invalid YAML frontmatter: {e}")

    if "NO_PATCH:" in evolved and "NO_PATCH:" not in current_skill:
        issues.append("Analyst leak detected: 'NO_PATCH:'")

    adk_vars = _ADK_VAR_RE.findall(evolved)
    unsafe = [v for v in adk_vars if v not in _ADK_KNOWN_VARS]
    if unsafe:
        issues.append(
            f"ADK context variable collision: {{{unsafe[0]}}} "
            f"(and {len(unsafe)-1} more). Will crash at runtime."
        )

    # Size: evolved should be at least as large as current (not truncated)
    if len(evolved) < len(current_skill):
        issues.append(
            f"Smaller than input ({len(evolved)} < {len(current_skill)} chars). "
            "Likely truncated."
        )

    # Structure: evolved skill should have sections
    headers = [line for line in evolved.split("\n") if line.startswith("## ")]
    if len(headers) < 2:
        issues.append(
            f"Too few sections ({len(headers)} '##' headers). "
            "Skill may be incomplete."
        )

    # Diff-guard (AutoSkill P_merge / Trace2Skill guardrail): accumulative
    # merge must not DROP existing sections. Every '## '/'### ' heading in the
    # base skill must survive in the evolved skill. A dropped heading is the
    # signature of a rewrite-from-scratch that lost content (the observed
    # 51-63% candidate collapses).
    def _headings(text: str) -> set[str]:
        return {
            line.strip().lstrip("#").strip().lower()
            for line in text.split("\n")
            if line.startswith("## ") or line.startswith("### ")
        }

    base_headings = _headings(current_skill)
    evolved_headings = _headings(evolved)
    dropped = sorted(base_headings - evolved_headings)
    if dropped:
        preview = ", ".join(dropped[:3])
        more = f" (and {len(dropped) - 3} more)" if len(dropped) > 3 else ""
        issues.append(
            f"Dropped {len(dropped)} base section(s): {preview}{more}. "
            "Accumulative merge must preserve every existing section."
        )

    return issues


def compute_prevalence_summary(patches: list[str]) -> str:
    """Count root cause categories across patches for consolidator context.

    Trace2Skill principle: edits appearing across many independent patches
    are systematic. Edits in 1-2 patches are idiosyncratic.
    """
    import re
    from collections import Counter

    category_counts = Counter()
    for patch in patches:
        match = re.search(r"## Root Cause\s*\n\s*\[?(\w+)\]?", patch)
        if not match:
            match = re.search(r"## Pattern\s*\n\s*\[?(\w+)\]?", patch)
        if match:
            category_counts[match.group(1)] += 1

    if not category_counts:
        return ""

    total = len(patches)
    lines = [f"Prevalence across {total} independent analyst patches:"]
    for cat, count in category_counts.most_common():
        pct = round(count / total * 100)
        strength = "STRONG" if count >= 3 else "moderate" if count >= 2 else "weak"
        lines.append(f"  {cat}: {count}/{total} patches ({pct}%) — {strength} signal")

    return "\n".join(lines)


def run_consolidator(
    client: genai.Client,
    model_id: str,
    current_skill: str,
    patches: list[str],
    summary: dict,
    temperature: float = 0.2,
    template: str | None = None,
) -> str:
    """Consolidate all patches into an evolved skill document."""
    patches_text = "\n\n---\n\n".join(
        [f"### Patch {i + 1}\n{p}" for i, p in enumerate(patches)]
    )
    prevalence = compute_prevalence_summary(patches)
    prompt = (
        f"<base_skill>\n{current_skill}\n</base_skill>\n\n"
        f"The base_skill above is your STARTING POINT. Merge the analyst "
        f"patches INTO it as a semantic union. Keep every existing section "
        f"and rule unless a patch explicitly corrects it. Never drop a "
        f"section.\n\n"
        f"<quality_summary>\n"
        f"Total sessions: {summary.get('total_sessions', 0)}\n"
        f"Meaningful: {summary.get('meaningful', 0)}\n"
        f"Declined (correct): {summary.get('declined', 0)}\n"
        f"Unhelpful: {summary.get('unhelpful', 0)}\n"
        f"Partial: {summary.get('partial', 0)}\n"
        f"Meaningful rate: {summary.get('meaningful_rate', 0)}%\n"
        f"</quality_summary>\n\n"
    )
    if prevalence:
        prompt += f"<prevalence_summary>\n{prevalence}\n</prevalence_summary>\n\n"
    prompt += f"<analyst_patches>\n{patches_text}\n</analyst_patches>\n\n"
    if template:
        prompt += (
            f"<template>\n{template}\n</template>\n\n"
            f"IMPORTANT: Use the template above as the structural blueprint. "
            f"Your output MUST follow the same section structure, headings, "
            f"and formatting style. Integrate analyst patches into the template's "
            f"sections. Do NOT invent new sections or reorganize.\n\n"
        )
    prompt += (
        f"Produce the complete MERGED SKILL.md content (base_skill + patches, "
        f"semantic union, no section dropped). "
        f"Output ONLY the file content (frontmatter + body), nothing else."
    )
    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=CONSOLIDATOR_PROMPT,
            temperature=temperature,
            max_output_tokens=16384,
        ),
    )
    result = strip_code_fences(response.text.strip())
    if len(result) < 50:
        logger.warning(
            "Consolidator returned near-empty result (%d chars). "
            "Retrying once with higher temperature...", len(result),
        )
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=CONSOLIDATOR_PROMPT,
                temperature=min(temperature + 0.3, 1.0),
                max_output_tokens=16384,
            ),
        )
        result = strip_code_fences(response.text.strip())
    return result


def run_compaction(
    client: genai.Client,
    model_id: str,
    skill: str,
    max_chars: int,
) -> str:
    """Compact an evolved skill that exceeds max_chars."""
    if len(skill) <= max_chars:
        return skill

    logger.info(
        "Skill is %d chars (limit %d). Running compaction...",
        len(skill), max_chars,
    )
    prompt = (
        f"<skill>\n{skill}\n</skill>\n\n"
        f"Compact this skill to under {max_chars} characters. "
        f"Output ONLY the compacted SKILL.md content."
    )
    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=COMPACTION_PROMPT.format(max_chars=max_chars),
            temperature=0.1,
        ),
    )
    compacted = strip_code_fences(response.text.strip())
    logger.info("Compacted: %d -> %d chars", len(skill), len(compacted))
    return compacted


def run_batch_consolidator(
    client: genai.Client,
    model_id: str,
    current_skill: str,
    patches: list[str],
    batch_index: int,
) -> str:
    """Consolidate a batch of patches into an intermediate skill fragment."""
    patches_text = "\n\n---\n\n".join(
        [f"### Patch {i + 1}\n{p}" for i, p in enumerate(patches)]
    )
    prompt = (
        f"<current_skill>\n{current_skill}\n</current_skill>\n\n"
        f"<analyst_patches>\n{patches_text}\n</analyst_patches>\n\n"
        f"This is batch {batch_index + 1}. Merge these patches into a "
        f"coherent set of improvements. Output a consolidated patch document "
        f"that preserves all actionable insights, deduplicates overlapping "
        f"suggestions, and resolves conflicts."
    )
    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=HIERARCHICAL_CONSOLIDATOR_PROMPT,
            temperature=0.2,
        ),
    )
    return response.text.strip()


def run_hierarchical_consolidation(
    client: genai.Client,
    model_id: str,
    current_skill: str,
    patches: list[str],
    summary: dict,
    batch_size: int = 7,
    max_workers: int = 5,
    temperature: float = 0.2,
) -> str:
    """Hierarchical consolidation: batch patches → intermediate merges → final merge.

    Closer to Trace2Skill's recursive tree merge approach.
    """
    if len(patches) <= batch_size:
        logger.info("Only %d patches, using flat consolidation", len(patches))
        return run_consolidator(client, model_id, current_skill, patches, summary, temperature=temperature)

    batches = [
        patches[i : i + batch_size]
        for i in range(0, len(patches), batch_size)
    ]
    logger.info(
        "Hierarchical consolidation: %d patches → %d batches of ≤%d",
        len(patches), len(batches), batch_size,
    )

    intermediate_results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                run_batch_consolidator, client, model_id, current_skill,
                batch, idx,
            ): idx
            for idx, batch in enumerate(batches)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                result = fut.result()
                intermediate_results.append((idx, result))
                logger.info("  Batch %d/%d consolidated", idx + 1, len(batches))
            except Exception as e:
                logger.warning("  Batch %d FAILED: %s", idx + 1, e)

    intermediate_results.sort(key=lambda x: x[0])
    merged_patches = [r for _, r in intermediate_results]

    logger.info("Final consolidation of %d intermediate results...", len(merged_patches))
    return run_consolidator(client, model_id, current_skill, merged_patches, summary, temperature=temperature)


def _save_artifact(artifacts_dir: str | None, name: str, data) -> None:
    """Save an intermediate artifact to the artifacts directory."""
    if not artifacts_dir:
        return
    path = os.path.join(artifacts_dir, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, str):
        with open(path, "w") as f:
            f.write(data)
    else:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    logger.info("Artifact: %s (%s)", name, _file_size(path))


def _file_size(path: str) -> str:
    size = os.path.getsize(path)
    if size < 1024:
        return f"{size}B"
    return f"{size / 1024:.1f}KB"


def collect_patches(
    report_path: str,
    skill_dir: str,
    model_id: str = "gemini-2.5-flash",
    max_workers: int = 10,
    max_success_samples: int = 15,
    analyst_mode: str = "both",
    agentic: bool = False,
    score_patches: bool = False,
    artifacts_dir: str | None = None,
) -> tuple[list[str], str, dict, genai.Client]:
    """Run analyst fleet and collect patches. Returns (patches, current_skill, summary, client).

    This is the expensive step (one API call per trajectory). Separated from
    consolidation so that best-of-N can run analysts once and consolidate N times.

    Args:
        analyst_mode: "both" (default), "error-only", or "success-only".
        agentic: Use agentic error analysts with tool access for investigation.
        score_patches: Score patches on quality before returning.
        artifacts_dir: If set, dump each sub-step's output to this directory.
    """
    with open(report_path) as f:
        report = json.load(f)
    current_skill = load_current_skill(skill_dir)
    summary = report.get("summary", {})

    successes, failures = partition_trajectories(report)
    total = len(successes) + len(failures)
    logger.info(
        "Trajectories: %d total (%d successes, %d failures)",
        total, len(successes), len(failures),
    )

    # Artifact 3a: trajectory partitions
    _save_artifact(artifacts_dir, "3a_t_plus.json", [
        {"session_id": s.get("session_id"), "question": s.get("question", ""),
         "verdict": s.get("metrics", {}).get("response_usefulness", {}).get("category", "")}
        for s in successes
    ])
    _save_artifact(artifacts_dir, "3a_t_minus.json", [
        {"session_id": s.get("session_id"), "question": s.get("question", ""),
         "verdict": s.get("metrics", {}).get("response_usefulness", {}).get("category", ""),
         "corrections": s.get("corrections", 0),
         "correction_boundaries": s.get("correction_boundaries", [])}
        for s in failures
    ])

    if total == 0:
        logger.warning("No trajectories to analyze.")
        return [], current_skill, summary, None

    client = genai.Client(
        vertexai=True,
        project=os.getenv("PROJECT_ID"),
        location=os.getenv("REGION", "us-central1"),
    )

    # Apply analyst mode filter
    if analyst_mode == "error-only":
        successes_to_use = []
        failures_to_use = failures
    elif analyst_mode == "success-only":
        successes_to_use = successes[:max_success_samples]
        failures_to_use = []
    else:
        successes_to_use = successes[:max_success_samples]
        failures_to_use = failures

    # Lazy import for agentic analysts to avoid circular imports
    agentic_analyst_fn = None
    if agentic:
        from agents.workflow.skill_evolution_agent.agentic_analyst import run_agentic_analyst
        agentic_analyst_fn = run_agentic_analyst
        logger.info("Using agentic error analysts with tool access")

    # Artifact 3b-input: formatted trajectories sent to analysts
    if artifacts_dir:
        formatted = []
        for s in failures_to_use:
            formatted.append({"session_id": s.get("session_id"), "type": "error",
                              "formatted": format_trajectory(s)})
        for s in successes_to_use:
            formatted.append({"session_id": s.get("session_id"), "type": "success",
                              "formatted": format_trajectory(s)})
        _save_artifact(artifacts_dir, "3b_formatted_trajectories.json", formatted)

    logger.info(
        "Dispatching analyst fleet (%d error + %d success analysts, mode=%s, agentic=%s)...",
        len(failures_to_use), len(successes_to_use), analyst_mode, agentic,
    )
    patches = []
    analyst_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}

        for session in failures_to_use:
            if agentic_analyst_fn:
                fut = executor.submit(
                    agentic_analyst_fn, client, model_id,
                    session, current_skill,
                )
            else:
                fut = executor.submit(
                    run_analyst, client, model_id, ERROR_ANALYST_PROMPT,
                    session, current_skill,
                )
            futures[fut] = ("error", session.get("question", "")[:60])

        for session in successes_to_use:
            fut = executor.submit(
                run_analyst, client, model_id, SUCCESS_ANALYST_PROMPT,
                session, current_skill,
            )
            futures[fut] = ("success", session.get("question", "")[:60])

        for fut in as_completed(futures):
            analyst_type, question = futures[fut]
            analyst_count += 1
            try:
                result = fut.result()
                if result:
                    patches.append(result)
                    logger.info(
                        "  [%d/%d] [%s] %s -> patch",
                        analyst_count, len(futures), analyst_type, question,
                    )
                else:
                    logger.info(
                        "  [%d/%d] [%s] %s -> no patch",
                        analyst_count, len(futures), analyst_type, question,
                    )
            except Exception as e:
                logger.warning(
                    "  [%d/%d] [%s] %s -> FAILED: %s",
                    analyst_count, len(futures), analyst_type, question, e,
                )

    logger.info("Collected %d patches from %d analysts", len(patches), analyst_count)

    # Artifact 3b-output: raw patches before quality gate
    if artifacts_dir:
        for i, p in enumerate(patches):
            _save_artifact(artifacts_dir, f"3b_patches_raw/patch_{i + 1:03d}.md", p)

    # Quality gate
    pre_gate = len(patches)
    patches = [p for p in patches if passes_quality_gate(p)]
    rejected = pre_gate - len(patches)
    if rejected:
        logger.info("Quality gate rejected %d/%d patches", rejected, pre_gate)

    # Artifact 3c: filtered patches + gate summary
    if artifacts_dir:
        for i, p in enumerate(patches):
            _save_artifact(artifacts_dir, f"3c_patches_filtered/patch_{i + 1:03d}.md", p)
        _save_artifact(artifacts_dir, "3c_quality_gate.json", {
            "total_raw": pre_gate,
            "passed": len(patches),
            "rejected": rejected,
        })

    # Optional: LLM-based patch quality scoring
    if score_patches and patches:
        from agents.workflow.skill_evolution_agent.patch_scoring import (
            annotate_patches_for_consolidator,
            score_and_rank_patches,
        )
        scored = score_and_rank_patches(
            client, model_id, patches, current_skill,
            min_score=0.4, max_workers=max_workers,
        )
        patches = annotate_patches_for_consolidator(scored)

    return patches, current_skill, summary, client


def consolidate_once(
    client: genai.Client,
    model_id: str,
    current_skill: str,
    patches: list[str],
    summary: dict,
    hierarchical: bool = False,
    temperature: float = 0.2,
    max_workers: int = 10,
    template: str | None = None,
    max_chars: int | None = None,
) -> str:
    """Run consolidation once. Returns evolved skill content."""
    if hierarchical:
        evolved = run_hierarchical_consolidation(
            client, model_id, current_skill, patches, summary,
            max_workers=max_workers, temperature=temperature,
        )
    else:
        evolved = run_consolidator(
            client, model_id, current_skill, patches, summary,
            temperature=temperature, template=template,
        )
    issues = validate_evolved_skill(evolved, current_skill)
    if issues:
        logger.warning("Guardrail issues: %s. Retrying with higher temperature...", issues)
        if hierarchical:
            evolved = run_hierarchical_consolidation(
                client, model_id, current_skill, patches, summary,
                max_workers=max_workers, temperature=min(temperature + 0.3, 1.0),
            )
        else:
            evolved = run_consolidator(
                client, model_id, current_skill, patches, summary,
                temperature=min(temperature + 0.3, 1.0), template=template,
            )
        retry_issues = validate_evolved_skill(evolved, current_skill)
        if retry_issues:
            logger.error("Guardrail issues persist after retry: %s. Using current skill.", retry_issues)
            return current_skill

    if max_chars and len(evolved) > max_chars:
        evolved = run_compaction(client, model_id, evolved, max_chars)
    return evolved


def evolve(
    report_path: str,
    skill_dir: str,
    model_id: str = "gemini-2.5-flash",
    max_workers: int = 10,
    max_success_samples: int = 15,
    hierarchical: bool = False,
    temperature: float = 0.2,
    candidates: int | None = None,
    candidates_dir: str | None = None,
    template_path: str | None = None,
    max_chars: int | None = None,
    analyst_mode: str = "both",
    agentic: bool = True,
    score_patches: bool = False,
    artifacts_dir: str | None = None,
    score_fn=None,
    incumbent_score: float | None = None,
    min_improvement: float = 0.5,
) -> str:
    """Run the full skill evolution pipeline.

    Args:
        report_path: Path to quality report JSON file.
        skill_dir: Path to skill directory containing SKILL.md.
        model_id: Gemini model for analyst and consolidator calls.
        max_workers: Maximum parallel analyst threads.
        max_success_samples: Max success trajectories to analyze.
        hierarchical: Use hierarchical (tree) consolidation instead of flat.
        temperature: Consolidator temperature (default 0.2).
        candidates: Number of consolidation candidates to generate (best-of-N).
            When > 1, runs consolidator N times in parallel from the same
            patches and saves all candidates to candidates_dir.
            When None, auto-decides based on meaningful_rate: >=90% → 1,
            >=80% → 3, <80% → 5.
        candidates_dir: Directory to save candidate skills when candidates > 1.
            Each candidate is saved as candidate_1.md, candidate_2.md, etc.
        template_path: Path to a skill file to use as structural template.
            The consolidator will follow this template's section structure.
        max_chars: Maximum character count for evolved skill. If exceeded,
            a compaction pass distills the skill while preserving key rules.
        agentic: Use agentic error analysts with tool access (default: True,
            per Trace2Skill finding that agentic outperforms single-pass).
        score_patches: Score patches on quality before consolidation.
        artifacts_dir: If set, dump every sub-step's output to this directory
            for debugging and inspection. Structure:
              3a_t_plus.json, 3a_t_minus.json
              3b_formatted_trajectories.json, 3b_patches_raw/
              3c_patches_filtered/, 3c_quality_gate.json
              3d_prevalence.json, 3d_evolved_skill.md
              3e_validation.json, 3e_compacted_skill.md (if compacted)

    Returns:
        The evolved SKILL.md content as a string (the best candidate if N > 1,
        or the only candidate if N == 1).
    """
    t0 = time.time()

    # Load template if provided
    template = None
    if template_path:
        with open(template_path) as f:
            template = f.read()
        logger.info("Using structural template from %s (%d chars)", template_path, len(template))

    # Step 1: Collect patches (expensive — one API call per trajectory)
    patches, current_skill, summary, client = collect_patches(
        report_path, skill_dir, model_id, max_workers, max_success_samples,
        analyst_mode=analyst_mode, agentic=agentic,
        score_patches=score_patches,
        artifacts_dir=artifacts_dir,
    )

    if not patches:
        logger.warning("No patches to consolidate. Returning current skill.")
        return current_skill

    # Artifact 3d: prevalence summary
    prevalence = compute_prevalence_summary(patches)
    if prevalence:
        _save_artifact(artifacts_dir, "3d_prevalence.txt", prevalence)

    # Auto-decide candidates based on quality score.
    # EVOLUTION_CANDIDATES (set by main.py from --candidates) is BINDING:
    # it wins over the rate-based auto-selection so demo runs stay bounded.
    if candidates is None and os.getenv("EVOLUTION_CANDIDATES"):
        candidates = int(os.environ["EVOLUTION_CANDIDATES"])
        logger.info("Candidates bound by EVOLUTION_CANDIDATES=%d", candidates)
    if candidates is None:
        rate = summary.get("meaningful_rate", 0)
        if rate >= 90:
            candidates = 1
        elif rate >= 80:
            candidates = 3
        else:
            candidates = 5
        logger.info(
            "Auto-selected candidates=%d (meaningful_rate=%.1f%%)", candidates, rate,
        )

    # Step 2: Consolidate (cheap — one API call per candidate)
    if candidates <= 1:
        logger.info("Single consolidation of %d patches (temperature=%.2f)...", len(patches), temperature)
        evolved = consolidate_once(
            client, model_id, current_skill, patches, summary,
            hierarchical=hierarchical, temperature=temperature,
            max_workers=max_workers, template=template,
            max_chars=max_chars,
        )
        if len(evolved) < 50:
            logger.error(
                "Evolution produced near-empty skill (%d chars). "
                "Falling back to current skill.", len(evolved),
            )
            evolved = current_skill

        # Artifact 3d: consolidated skill (before compaction)
        _save_artifact(artifacts_dir, "3d_evolved_skill.md", evolved)

        # Artifact 3e: validation result
        issues = validate_evolved_skill(evolved, current_skill)
        _save_artifact(artifacts_dir, "3e_validation.json", {
            "issues": issues,
            "evolved_chars": len(evolved),
            "original_chars": len(current_skill),
            "ratio": round(len(evolved) / max(len(current_skill), 1), 2),
        })

        evolved = sanitize_adk_vars(evolved)

        elapsed = time.time() - t0
        logger.info("Evolution complete in %.1fs", elapsed)
        return evolved

    # Best-of-N: run consolidator N times in parallel
    logger.info(
        "Best-of-%d: running %d consolidations from %d patches (temperature=%.2f)...",
        candidates, candidates, len(patches), temperature,
    )

    candidate_skills = []
    with ThreadPoolExecutor(max_workers=min(candidates, 5)) as executor:
        futures = {
            executor.submit(
                consolidate_once, client, model_id, current_skill,
                patches, summary, hierarchical, temperature, max_workers,
                template, max_chars,
            ): i
            for i in range(candidates)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                skill = sanitize_adk_vars(fut.result())
                if len(skill) < 50:
                    logger.warning("  Candidate %d/%d near-empty (%d chars), skipping",
                                   idx + 1, candidates, len(skill))
                    continue
                candidate_skills.append((idx, skill))
                logger.info("  Candidate %d/%d generated (%d chars)",
                            idx + 1, candidates, len(skill))
            except Exception as e:
                logger.warning("  Candidate %d FAILED: %s", idx + 1, e)

    candidate_skills.sort(key=lambda x: x[0])

    if not candidate_skills:
        logger.warning("All candidates failed. Returning current skill.")
        return current_skill

    # Save all candidates to disk
    if candidates_dir:
        os.makedirs(candidates_dir, exist_ok=True)
        for idx, skill in candidate_skills:
            path = os.path.join(candidates_dir, f"candidate_{idx + 1}.md")
            with open(path, "w") as f:
                f.write(skill)
            logger.info("  Saved candidate %d to %s", idx + 1, path)

    elapsed = time.time() - t0
    logger.info(
        "Best-of-%d complete in %.1fs. %d candidates generated. "
        "Candidates saved to %s — score each and pick the best.",
        candidates, elapsed, len(candidate_skills),
        candidates_dir or "stdout",
    )

    # Diff-guard (AutoSkill P_merge / Trace2Skill guardrails): reject any
    # candidate that dropped a base section or was truncated, BEFORE scoring,
    # so a content-losing candidate can never be selected. This is the fix for
    # the observed 51-63% candidate collapses (rewrite-from-scratch content loss).
    viable = []
    for i, s in candidate_skills:
        issues = validate_evolved_skill(s, current_skill)
        hard = [
            x for x in issues
            if x.startswith("Dropped")
            or "Smaller than input" in x
            or "Too few sections" in x
        ]
        if hard:
            logger.warning(
                "  Candidate %d rejected by diff-guard: %s", i + 1, hard[0]
            )
            continue
        viable.append((i, s))
    if not viable:
        # Everything tripped the guard — fall back to the least-broken (largest)
        # so the loop still returns something, but log loudly.
        logger.warning(
            "All %d candidates failed the diff-guard; falling back to largest.",
            len(candidate_skills),
        )
        viable = sorted(candidate_skills, key=lambda x: -len(x[1]))[:1]

    # Deterministic score-based selection: score every viable candidate on the
    # eval set and keep the best ONLY if it beats the incumbent by a margin
    # (Trace2Skill eq.3 P(S*)>P(S0); AutoSkill "avoid regressions"). This
    # replaces the old median-by-size heuristic, which could ship a worse skill.
    if score_fn is not None:
        scored = []
        for i, s in viable:
            try:
                sc = score_fn(s)
            except Exception as e:  # noqa: BLE001
                logger.warning("  Candidate %d scoring failed: %s", i + 1, e)
                continue
            logger.info("  Candidate %d scored %.1f%% meaningful", i + 1, sc)
            scored.append((sc, i, s))
        if scored:
            scored.sort(key=lambda x: -x[0])
            best_score, best_i, best_s = scored[0]
            if (incumbent_score is not None
                    and best_score < incumbent_score + min_improvement):
                logger.info(
                    "Best candidate %d (%.1f%%) does not beat incumbent "
                    "(%.1f%% + %.1f margin) — keeping current skill.",
                    best_i + 1, best_score, incumbent_score, min_improvement,
                )
                # Evolved system == incumbent (no change deployed).
                _record_evolved_score(candidates_dir, incumbent_score)
                return current_skill
            logger.info(
                "Selected candidate %d by score: %.1f%% (incumbent %s).",
                best_i + 1, best_score,
                f"{incumbent_score:.1f}%" if incumbent_score is not None
                else "n/a",
            )
            # Authoritative score for the deployed skill, scored on the same
            # eval set as V0 — compare_versions uses this instead of re-scoring
            # versions on separate (noisy) traffic.
            _record_evolved_score(candidates_dir, best_score)
            return best_s
        logger.warning(
            "All candidate scoring failed — falling back to size selection.")

    # Fallback (no score_fn): median by size avoids truncated runts and bloat.
    viable.sort(key=lambda x: len(x[1]))
    selected = viable[len(viable) // 2]
    logger.info(
        "Auto-selected candidate %d (%d chars) — median of %d viable candidates",
        selected[0] + 1, len(selected[1]), len(viable),
    )
    return selected[1]


def _main() -> None:
    """CLI: consolidate a skill from a quality report. Writes the evolved skill
    to --output (and candidates to --candidates-dir). Does not deploy."""
    import argparse

    ap = argparse.ArgumentParser(description="Evolve a SKILL.md from a quality report.")
    ap.add_argument("--report", required=True, help="quality report JSON (failures to learn from)")
    ap.add_argument("--skill-dir", required=True, help="dir containing the agent's SKILL.md")
    ap.add_argument("--model", default="gemini-2.5-pro", help="analyst/consolidator model")
    ap.add_argument("--candidates", type=int, default=None)
    ap.add_argument("--candidates-dir", default=None)
    ap.add_argument("--max-chars", type=int, default=None, help="cap evolved skill size (forces conciseness)")
    ap.add_argument("--max-workers", type=int, default=10)
    ap.add_argument("--no-agentic", action="store_true", help="disable agentic analysts")
    ap.add_argument("--artifacts-dir", default=None)
    ap.add_argument("-o", "--output", required=True, help="where to write the evolved SKILL.md")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO)
    evolved = evolve(
        report_path=args.report,
        skill_dir=args.skill_dir,
        model_id=args.model,
        max_workers=args.max_workers,
        candidates=args.candidates,
        candidates_dir=args.candidates_dir,
        max_chars=args.max_chars,
        agentic=not args.no_agentic,
        artifacts_dir=args.artifacts_dir,
    )
    with open(args.output, "w") as f:
        f.write(evolved)
    print(f"evolved skill written to {args.output} ({len(evolved)} chars)")


if __name__ == "__main__":
    _main()


