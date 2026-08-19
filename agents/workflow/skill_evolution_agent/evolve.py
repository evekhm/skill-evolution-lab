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

"""Skill Evolution Pipeline — adapter over the SDK evolution engine.

The evolution algorithm (analyst fleet, quality gate, consolidation,
structural guardrails, best-of-N selection with the incumbent guard) lives
in the BigQuery-Agent-Analytics-SDK as ``scripts/skill_evolution.py`` and is
imported here via ``ensure_sdk`` — the SDK is the single source of truth for
the algorithm (Trace2Skill arXiv:2603.25158, AutoSkill arXiv:2603.01145;
references in the SDK module).

This module supplies only what is lab-specific:
- the Vertex client built from the lab's env (PROJECT_ID, MODEL_LOCATION),
- the agentic error analyst (tool-using investigator) via the engine's
  ``error_analyst_fn`` hook,
- demo-run knobs (EVOLUTION_MAX_ANALYSTS stride sampling,
  EVOLUTION_CANDIDATES binding, rate-based candidate auto-count),
- the flat ``candidate_N.md`` layout in candidates_dir and the
  ``evolved_score.json`` record that compare_versions consumes.

Library module — invoked via tools.py (ADK agent) or main.py (CLI).
"""

import glob
import json
import logging
import os
import re
import shutil
import sys
import time

from google import genai

# Allow running from project root; repo root also hosts ensure_sdk.py
# (copied into /app in Docker), matching quality_report.py's pattern.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, PROJECT_ROOT)

from ensure_sdk import import_sdk_module  # noqa: E402

logger = logging.getLogger(__name__)

_ENGINE = None


def _engine():
    """The SDK evolution engine module (imported once, on first use)."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = import_sdk_module("skill_evolution")
    return _ENGINE


# ---------------------------------------------------------------------------
# Re-exports — these names are part of this module's API and are imported by
# agentic_analyst.py, bottleneck.py, and coevolve.py. They delegate to the
# SDK engine so there is exactly one implementation.
# ---------------------------------------------------------------------------


def _format_conversation(conversation) -> str:
    """Format a conversation into readable text (SDK engine)."""
    return _engine()._format_conversation(conversation)


def format_trajectory(session: dict) -> str:
    """Format a session dict for analyst consumption (SDK engine)."""
    return _engine().format_trajectory(session)


def partition_trajectories(report: dict) -> tuple[list, list]:
    """Split sessions into successes (T+) and failures (T-) (SDK engine)."""
    return _engine().partition_trajectories(report)


def validate_evolved_skill(evolved: str, current_skill: str) -> list[str]:
    """Structural guardrail check; empty list = valid (SDK engine)."""
    return _engine().validate_evolved_skill(evolved, current_skill)


def sanitize_adk_vars(skill: str) -> str:
    """Escape {identifier} patterns ADK would resolve as state (SDK engine)."""
    return _engine().sanitize_adk_vars(skill)


# ---------------------------------------------------------------------------
# Lab-specific plumbing
# ---------------------------------------------------------------------------


_toolbox_cache: dict[str, str] = {}


def _derive_toolbox(agent: str | None = None) -> str:
    """The target agent's toolbox, DERIVED from its live definition.

    Introspects the same in-process agent objects candidate scoring
    builds: AgentTools contribute the sub-agent's name and description,
    function tools their name and docstring first line. Nothing is
    hand-maintained — the block always matches the code that runs.
    Analysts previously had to infer the toolbox from trajectories, so
    baselines whose conversations showed few tool calls (deployed serve
    paths suppress discretionary tool use) produced vague, weak skills.
    Returns "" when the agent cannot be introspected.

    Fed to the SDK engine via ``evolve_skill(tools=...)`` (the engine
    shows it to every analyst and the consolidator); the agentic analyst
    prepends it to its own prompt directly.
    """
    agent = (agent or os.getenv("EVOLUTION_TARGET_AGENTS", "supervisor")
             ).split(",")[0].strip()
    if agent in _toolbox_cache:
        return _toolbox_cache[agent]
    try:
        from agents.workflow.traffic_generator.main import _build_local_supervisor
        root = _build_local_supervisor(local_agents=True)
        if agent in ("supervisor", root.name):
            target = root
        else:
            target = next(
                (getattr(t, "agent", None) for t in root.tools
                 if getattr(getattr(t, "agent", None), "name", None) == agent),
                None,
            )
        if target is None:
            _toolbox_cache[agent] = ""
            return ""
        lines = []
        for t in target.tools:
            sub = getattr(t, "agent", None)
            if sub is not None:
                desc = " ".join((sub.description or "").split())
                lines.append(f"- `{sub.name}` (callable as a tool): {desc}")
            else:
                name = getattr(t, "__name__", None) or getattr(t, "name", str(t))
                doc = ((getattr(t, "__doc__", "") or "").strip().split("\n") or [""])[0]
                lines.append(f"- `{name}`: {doc}")
        block = (
            "<agent_toolbox>\n"
            "The agent HAS these callable tools (read from its live "
            "definition; true even when the trajectories show few or no "
            "tool calls — a failing baseline under-using its tools IS the "
            "defect, not the toolbox):\n"
            + "\n".join(lines) + "\n"
            "An evolved skill should direct the agent to use these tools "
            "BY NAME wherever they resolve the observed failures.\n"
            "</agent_toolbox>\n\n"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Toolbox derivation failed for %s: %s", agent, e)
        block = ""
    _toolbox_cache[agent] = block
    return block


def load_current_skill(skill_dir: str) -> str:
    """Read the full SKILL.md content from the skill directory."""
    skill_path = os.path.join(skill_dir, "SKILL.md")
    with open(skill_path) as f:
        return f.read()


def _record_evolved_score(candidates_dir: str | None, score: float | None,
                          unmeasurable: bool = False) -> None:
    """Persist the deployed skill's authoritative selection score.

    Written to ``<run_dir>/evolved_score.json`` so ``compare_versions`` reports
    the same score the incumbent-guarded selection used, rather than re-scoring
    versions on separate (noisy) traffic. Last writer wins, which is correct:
    in sequential co-evolution the final agent is scored against the others'
    already-deployed winners, so it reflects the full evolved system.
    """
    if not candidates_dir or (score is None and not unmeasurable):
        return
    try:
        run_dir = os.path.dirname(candidates_dir.rstrip("/"))
        payload = {"version": "evolved", "meaningful_rate": score}
        if unmeasurable:
            # Explicit null marker (review R6-4 on #106): in co-evolution
            # the file is shared across agents, and writing nothing would
            # leave the PREVIOUS agent's score attributed to a system that
            # now includes this agent's skill. _refresh_incumbent treats a
            # null rate as keep-the-current-bar.
            payload["unmeasurable"] = True
        with open(os.path.join(run_dir, "evolved_score.json"), "w") as f:
            json.dump(payload, f)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not record evolved score: %s", e)


def _stride_sample_failures(report: dict) -> dict:
    """Apply EVOLUTION_MAX_ANALYSTS (set by --quick) to the report.

    Stride-samples the failures so every part of the failure distribution
    stays represented while the fleet stays demo-sized. Full runs leave the
    variable unset and get the report unchanged.
    """
    cap = os.getenv("EVOLUTION_MAX_ANALYSTS")
    if not cap:
        return report
    successes, failures = _engine().partition_trajectories(report)
    n = int(cap)
    if len(failures) <= n:
        return report
    stride = len(failures) / n
    sampled = [failures[int(i * stride)] for i in range(n)]
    logger.info(
        "EVOLUTION_MAX_ANALYSTS=%d: stride-sampled %d of %d failures",
        n, len(sampled), len(failures),
    )
    trimmed = dict(report)
    trimmed["sessions"] = successes + sampled
    return trimmed


def _auto_candidates(summary: dict) -> int:
    """Candidate count when the caller passed None.

    EVOLUTION_CANDIDATES (set by main.py from --candidates) is BINDING: it
    wins over the rate-based auto-selection so demo runs stay bounded.
    Otherwise: meaningful_rate >=90% → 1, >=80% → 3, <80% → 5.
    """
    if os.getenv("EVOLUTION_CANDIDATES"):
        candidates = int(os.environ["EVOLUTION_CANDIDATES"])
        logger.info("Candidates bound by EVOLUTION_CANDIDATES=%d", candidates)
        return candidates
    rate = summary.get("meaningful_rate", 0)
    candidates = 1 if rate >= 90 else 3 if rate >= 80 else 5
    logger.info(
        "Auto-selected candidates=%d (meaningful_rate=%.1f%%)", candidates, rate,
    )
    return candidates


def _version_label(current_skill: str) -> str:
    """Artifact prefix for the round being produced: base version + 1."""
    m = re.search(r'^version:\s*"?(\d+)"?', current_skill, re.MULTILINE)
    return f"v{int(m.group(1)) + 1}" if m else "v1"


def _flatten_candidates(candidates_dir: str) -> None:
    """Copy the engine's ``<label>_candidates/candidate_*.md`` up one level.

    tools.py and the demo flows list ``candidate_N.md`` directly in
    candidates_dir; the engine writes them under a version-labelled subdir
    (and tags the winner ``_SELECTED``). Keep both: the subdir stays as the
    audit artifact, the flat copies preserve the existing contract.
    """
    for path in sorted(glob.glob(
            os.path.join(candidates_dir, "*_candidates", "candidate_*.md"))):
        flat_name = os.path.basename(path).replace("_SELECTED", "")
        try:
            shutil.copyfile(path, os.path.join(candidates_dir, flat_name))
        except OSError as e:
            logger.warning("Could not flatten candidate %s: %s", path, e)


def evolve(
    report_path: str,
    skill_dir: str,
    model_id: str = os.getenv("EVOLUTION_MODEL_ID", "gemini-2.5-pro"),
    max_workers: int = 10,
    max_success_samples: int = 15,
    candidates: int | None = None,
    candidates_dir: str | None = None,
    max_chars: int | None = None,
    analyst_mode: str = "both",
    agentic: bool = True,
    artifacts_dir: str | None = None,
    score_fn=None,
    incumbent_score: float | None = None,
    min_improvement: float = 0.5,
) -> str:
    """Run the full skill evolution pipeline (SDK engine + lab adapters).

    Args:
        report_path: Path to quality report JSON file.
        skill_dir: Path to skill directory containing SKILL.md.
        model_id: Gemini model for analyst and consolidator calls.
        max_workers: Maximum parallel analyst threads.
        max_success_samples: Max success trajectories to analyze.
        candidates: Number of consolidation candidates (best-of-N).
            None = EVOLUTION_CANDIDATES env if set, else auto by
            meaningful_rate (>=90% → 1, >=80% → 3, <80% → 5).
        candidates_dir: Directory to save candidate skills; also anchors
            evolved_score.json one level up (the run dir).
        max_chars: Cap on evolved skill size; exceeding it triggers the
            engine's compaction pass.
        analyst_mode: "both" (default), "error-only", or "success-only".
        agentic: Use agentic error analysts with tool access (default True,
            per Trace2Skill finding that agentic outperforms single-pass).
        artifacts_dir: Where the engine writes patches/candidates/prevalence/
            selection artifacts. Defaults to candidates_dir.
        score_fn: Optional ``(skill_content) -> float`` for candidate
            selection; without it the engine picks the median-size viable
            candidate.
        incumbent_score: Pre-measured score of the current skill; the
            incumbent guard uses it instead of re-scoring V0.
        min_improvement: Margin a candidate must clear over the incumbent.

    Returns:
        The evolved SKILL.md content, or the unchanged current skill when
        no candidate clears the guardrails and the incumbent margin.
    """
    t0 = time.time()

    with open(report_path) as f:
        report = json.load(f)
    current_skill = load_current_skill(skill_dir)
    summary = report.get("summary", {})

    report = _stride_sample_failures(report)
    if candidates is None:
        candidates = _auto_candidates(summary)

    client = genai.Client(
        vertexai=True,
        project=os.getenv("PROJECT_ID"),
        location=os.getenv("MODEL_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "global",  # model endpoint: gemini-3.x is global-only
    )

    # Derive the toolbox HERE, before the engine spawns analyst threads:
    # derivation imports traffic_generator.main, whose import must happen
    # predictably in this thread, and one derivation serves every analyst.
    # The engine shows the block to all analysts and the consolidator.
    toolbox = _derive_toolbox() or None

    error_analyst_fn = None
    if agentic:
        # Lazy import to avoid circular imports
        from agents.workflow.skill_evolution_agent.agentic_analyst import (
            run_agentic_analyst,
        )

        def error_analyst_fn(client, model, session, skill, tools):  # noqa: ARG001
            return run_agentic_analyst(client, model, session, skill)

        logger.info("Using agentic error analysts with tool access")

    # Memoize candidate scores so the selected skill's score can be recorded
    # without re-scoring (compare_versions reads evolved_score.json).
    # score_fn may return None = unmeasurable (its report lost records to
    # the error-shaped preflight, review R5-3 on #106): floored to 0.0 for
    # selection so a flaked candidate cannot win, and NOT memoized so it is
    # never recorded as the authoritative deployed score / next incumbent
    # bar.
    scores: dict[str, float] = {}
    unmeasured: set[str] = set()
    wrapped_score_fn = None
    if score_fn is not None:
        def wrapped_score_fn(skill_content: str) -> float:
            raw = score_fn(skill_content)
            if raw is None:
                unmeasured.add(skill_content)
                logger.warning(
                    "Candidate score unmeasurable (preflight exclusions); "
                    "using 0.0 for selection, not recording it"
                )
                return 0.0
            score = float(raw)
            scores[skill_content] = score
            return score

    selected = _engine().evolve_skill(
        report,
        current_skill,
        model=model_id,
        max_workers=max_workers,
        max_success_samples=max_success_samples,
        candidates=candidates,
        max_chars=max_chars,
        analyst_mode=analyst_mode,
        score_fn=wrapped_score_fn,
        min_improvement=min_improvement,
        incumbent_score=incumbent_score,
        tools=toolbox,
        error_analyst_fn=error_analyst_fn,
        artifacts_dir=artifacts_dir or candidates_dir,
        version_label=_version_label(current_skill),
        client=client,
    )

    if candidates_dir and os.path.isdir(candidates_dir):
        _flatten_candidates(candidates_dir)

    # Authoritative score of the deployed outcome, on the same eval set as V0.
    if selected == current_skill:
        _record_evolved_score(candidates_dir, incumbent_score)
    elif selected in scores:
        _record_evolved_score(candidates_dir, scores[selected])
    elif selected in unmeasured:
        # Winner was scored and came back unmeasurable (its report lost
        # records to the preflight): write the explicit null marker (R6-4).
        _record_evolved_score(candidates_dir, None, unmeasurable=True)
    elif wrapped_score_fn is not None:
        # Memo miss without an unmeasurable verdict: the engine returned
        # content that is not byte-identical to what it scored (compaction
        # or sanitize after scoring, review R7-2 on #106). That is a key
        # mismatch, not a failed measurement — leave evolved_score.json
        # alone rather than overwrite a real score with a null.
        logger.warning(
            "Selected skill not found in the score memo (transformed "
            "after scoring?); evolved_score.json left unchanged"
        )

    logger.info("Evolution complete in %.1fs", time.time() - t0)
    return selected


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
