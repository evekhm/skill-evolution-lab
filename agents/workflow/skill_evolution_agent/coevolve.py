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

"""Cross-agent co-evolution orchestrator.

Uses bottleneck detection to identify which agent(s) to evolve, then
runs targeted evolution on the right agent(s). Prevents wasted cycles
evolving the wrong agent.

Library module — invoked via tools.py (ADK agent) or main.py (CLI).
"""

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from google import genai

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, PROJECT_ROOT)

from agents.workflow.skill_evolution_agent.bottleneck import detect_bottleneck
from agents.workflow.skill_evolution_agent.evolve import evolve, validate_evolved_skill

logger = logging.getLogger(__name__)

def _default_agent_configs() -> dict:
    try:
        from agents.workflow.skill_evolution_agent.tools import _AGENTS
        return _AGENTS
    except ImportError:
        return {}


@dataclass
class CoevolutionResult:
    """Result of a co-evolution run."""
    bottleneck_recommendation: str = ""
    bottleneck_summary: str = ""
    evolved_agents: dict = field(default_factory=dict)
    elapsed_seconds: float = 0.0

    @property
    def summary(self) -> str:
        agents = ", ".join(self.evolved_agents.keys()) or "none"
        return (
            f"Bottleneck: {self.bottleneck_recommendation}. "
            f"Evolved: {agents}. "
            f"Time: {self.elapsed_seconds:.1f}s"
        )


def coevolve(
    report_path: str,
    agent_configs: dict | None = None,
    output_dir: str | None = None,
    model_id: str = "gemini-2.5-flash",
    max_workers: int = 10,
    candidates: int | None = None,
    template_path: str | None = None,
    max_chars: int | None = None,
    agentic: bool = False,
    score_patches: bool = False,
    questions_file: str | None = None,
    select_by_score: bool = True,
) -> CoevolutionResult:
    """Run co-evolution: detect bottleneck, evolve the right agent(s).

    Args:
        report_path: Path to quality report JSON.
        agent_configs: Dict mapping agent name -> {skill_dir, label}.
            Defaults to agents from agent_registry.json.
        output_dir: Directory to save evolved skills and logs.
        model_id: Gemini model for all LLM calls.
        max_workers: Max parallel threads.
        candidates: Number of consolidation candidates (best-of-N).
            None = auto-decide based on meaningful_rate.
        template_path: Structural template for consolidation.
        max_chars: Max chars for evolved skill.
        agentic: Use agentic error analysts.
        score_patches: Score patches before consolidation.

    Returns:
        CoevolutionResult with bottleneck analysis and evolved skills.
    """
    t0 = time.time()
    configs = agent_configs or _default_agent_configs()
    result = CoevolutionResult()

    # Step 1: Load report and detect bottleneck
    with open(report_path) as f:
        report = json.load(f)

    client = genai.Client(
        vertexai=True,
        project=os.getenv("PROJECT_ID"),
        location=os.getenv("REGION", "us-central1"),
    )

    logger.info("Step 1: Detecting bottleneck...")
    bottleneck = detect_bottleneck(report, client, model_id)
    result.bottleneck_recommendation = bottleneck.recommendation
    result.bottleneck_summary = bottleneck.summary
    logger.info("Bottleneck: %s", bottleneck.summary)

    if bottleneck.recommendation == "none":
        logger.info("No failures to address. Skipping evolution.")
        result.elapsed_seconds = time.time() - t0
        return result

    # Step 2: Determine which agents to evolve
    rec = bottleneck.recommendation
    if rec == "both":
        agents_to_evolve = list(configs.keys())
    elif rec in configs:
        agents_to_evolve = [rec]
    elif rec == "none":
        agents_to_evolve = []
    else:
        fallback = list(configs.keys())[0] if configs else "unknown"
        logger.warning(
            "Unknown recommendation: %s. Defaulting to %s.",
            rec, fallback,
        )
        agents_to_evolve = [fallback]

    # Evolve the supervisor (routing) BEFORE the policy agent, so the policy
    # agent is scored against the already-improved routing (sequential
    # co-evolution, as the design intends).
    _ORDER = {"supervisor": 0, "knowledge_supervisor": 0}
    agents_to_evolve.sort(key=lambda n: _ORDER.get(n, 1))

    logger.info(
        "Step 2: Evolving %d agent(s) sequentially: %s",
        len(agents_to_evolve), agents_to_evolve,
    )

    # Incumbent baseline: never deploy a skill that scores worse than V0.
    incumbent_score = report.get("summary", {}).get("meaningful_rate")

    def _make_score_fn(skill_dir):
        """Score a candidate skill on the eval set; returns meaningful_rate."""
        if not (select_by_score and output_dir):
            return None

        def _score(skill_content):
            from agents.workflow.skill_evolution_agent.tools import (
                score_candidate,
            )
            tmp = os.path.join(output_dir, "_score_candidate_tmp.md")
            with open(tmp, "w") as fh:
                fh.write(skill_content)
            res = score_candidate(
                run_dir=output_dir, candidate_path=tmp, skill_dir=skill_dir,
                questions_file=questions_file,
            )
            return float(res.get("meaningful_rate", 0.0))

        return _score

    # Step 3: Evolve agents (with validation + retry)
    MAX_ATTEMPTS = 5

    def _evolve_agent(agent_name):
        config = configs.get(agent_name)
        if not config:
            logger.warning("No config for agent %s, skipping", agent_name)
            return agent_name, {"error": "no config"}

        skill_dir = config["skill_dir"]
        skill_path = os.path.join(skill_dir, "SKILL.md")
        label = config.get("label", agent_name)
        current_skill = ""
        if os.path.isfile(skill_path):
            with open(skill_path) as f:
                current_skill = f.read()

        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.info(
                "Evolving %s (attempt %d/%d, skill_dir=%s)...",
                label, attempt, MAX_ATTEMPTS, skill_dir,
            )

            cand_dir = None
            if output_dir:
                suffix = f"_retry{attempt}" if attempt > 1 else ""
                cand_dir = os.path.join(
                    output_dir, f"{agent_name}_candidates{suffix}",
                )
                os.makedirs(cand_dir, exist_ok=True)

            try:
                evolved = evolve(
                    report_path=report_path,
                    skill_dir=skill_dir,
                    model_id=model_id,
                    max_workers=max_workers,
                    candidates=candidates,
                    candidates_dir=cand_dir,
                    template_path=template_path,
                    max_chars=max_chars,
                    score_fn=_make_score_fn(skill_dir),
                    incumbent_score=incumbent_score,
                )

                issues = validate_evolved_skill(evolved, current_skill)
                if issues and attempt < MAX_ATTEMPTS:
                    logger.warning(
                        "Evolved %s failed validation (attempt %d): %s. Retrying...",
                        label, attempt, "; ".join(issues),
                    )
                    continue
                elif issues:
                    logger.warning(
                        "Evolved %s has issues after %d attempts: %s. Using best effort.",
                        label, attempt, "; ".join(issues),
                    )

                agent_result = {
                    "skill_dir": skill_dir,
                    "evolved_chars": len(evolved),
                    "candidates_dir": cand_dir,
                    "validation_issues": issues,
                    "attempt": attempt,
                }

                # Deploy the SELECTED winner to SKILL.md. score_candidate (used
                # during score-based selection) leaves the last-scored candidate
                # there, so we must write the actual winner back.
                with open(skill_path, "w") as f:
                    f.write(evolved)
                logger.info("Deployed selected %s skill to %s (%d chars)",
                            label, skill_path, len(evolved))

                if output_dir:
                    out_path = os.path.join(
                        output_dir, f"{agent_name}_evolved_skill.md",
                    )
                    with open(out_path, "w") as f:
                        f.write(evolved)
                    logger.info("Saved evolved %s skill to %s (%d chars)",
                                label, out_path, len(evolved))

                return agent_name, agent_result

            except Exception as e:
                logger.error("Failed to evolve %s (attempt %d): %s",
                             label, attempt, e)
                if attempt == MAX_ATTEMPTS:
                    return agent_name, {"error": str(e)}

        return agent_name, {"error": "exhausted retries"}

    # Sequential: each agent's candidate scoring runs full traffic on the
    # shared SKILL.md files, so parallel evolution would corrupt each other.
    for name in agents_to_evolve:
        agent_name, agent_result = _evolve_agent(name)
        result.evolved_agents[agent_name] = agent_result

    # Save co-evolution summary
    result.elapsed_seconds = time.time() - t0
    if output_dir:
        summary_path = os.path.join(output_dir, "coevolution_summary.json")
        summary = {
            "bottleneck": {
                "recommendation": bottleneck.recommendation,
                "confidence": bottleneck.confidence,
                "summary": bottleneck.summary,
                "routing_failures": len(bottleneck.routing_failures),
                "skill_failures": len(bottleneck.skill_failures),
                "tool_failures": len(bottleneck.tool_failures),
                "architecture_failures": len(bottleneck.architecture_failures),
            },
            "evolved_agents": result.evolved_agents,
            "elapsed_seconds": result.elapsed_seconds,
        }
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        logger.info("Co-evolution summary saved to %s", summary_path)

    logger.info("Co-evolution complete: %s", result.summary)
    return result


