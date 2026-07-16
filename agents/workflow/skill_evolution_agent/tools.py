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

"""Tools for the Skill Evolution Agent.

Wraps existing evolution pipeline modules (evolve.py, bottleneck.py,
coevolve.py) as ADK tool functions.  Also provides eval case extraction
using the shared ``eval/eval_cases.py`` module.

Full-loop tools (run_quality_report, upload_run_to_gcs,
create_evolution_pr) enable the agent to run the complete evolution
pipeline autonomously: traffic → score → evolve → upload → PR.
"""

import json
import logging
import os
import subprocess
import sys
import time

from google import genai

logger = logging.getLogger(__name__)

_script_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_script_dir, "../../.."))

# Ensure repo root is on sys.path for imports
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# Ensure eval/ is on sys.path for eval_cases import
_eval_dir = os.path.join(_repo_root, "eval")
if _eval_dir not in sys.path:
    sys.path.insert(0, _eval_dir)

# ---------------------------------------------------------------------------
# Agent registry
# ---------------------------------------------------------------------------


_DEFAULT_REGISTRY_PATHS = [
    os.path.join(_repo_root, "eval", "skill_evolution", "agent_registry.json"),
    os.path.join(_repo_root, "agent_registry.json"),
]


def _load_agent_registry(path: str | None = None) -> dict:
    if path is None:
        path = os.environ.get("AGENT_REGISTRY")
    if path is None:
        for candidate in _DEFAULT_REGISTRY_PATHS:
            if os.path.isfile(candidate):
                path = candidate
                break
    if not path or not os.path.isfile(path):
        logger.warning("No agent_registry.json found. Set AGENT_REGISTRY env var.")
        return {"agents": {}}
    with open(path) as f:
        registry = json.load(f)
    repo_root = registry.get("repo_root", _repo_root)
    for agent in registry["agents"].values():
        if not os.path.isabs(agent["skill_dir"]):
            agent["skill_dir"] = os.path.join(repo_root, agent["skill_dir"])
    logger.info("Loaded agent registry from %s (%d agents)", path, len(registry["agents"]))
    return registry


_REGISTRY = _load_agent_registry()
_AGENTS = _REGISTRY["agents"]
_DEFAULT_AGENT = next(iter(_AGENTS)) if _AGENTS else "unknown"


def _resolve_skill_dir(skill_dir: str) -> str:
    """Resolve agent name shortcut to absolute skill directory path."""
    if skill_dir in _AGENTS:
        return _AGENTS[skill_dir]["skill_dir"]
    return skill_dir


# ---------------------------------------------------------------------------
# Tool: run_evolution
# ---------------------------------------------------------------------------


def run_evolution(
    quality_report_path: str,
    skill_dir: str,
    run_dir: str | None = None,
    model_id: str = "gemini-2.5-flash",
    max_workers: int = 10,
    agentic: bool = True,
    candidates: int | None = None,
    max_chars: int = 25000,
) -> dict:
    """Run skill evolution on a single agent.

    Analyzes execution trajectories from a quality report and evolves
    the agent's SKILL.md through a parallel analyst fleet followed by
    patch consolidation.

    When candidates > 1, generates N candidate skills and saves them
    to run_dir as candidate_1.md, candidate_2.md, etc. The first
    candidate is deployed to SKILL.md. Call score_candidate on each
    to find the best, then restore_skills + deploy the winner.

    Args:
        quality_report_path: Path to quality report JSON file.
        skill_dir: Path to agent's skill directory containing SKILL.md.
            Agent name shortcuts from agent_registry.json are accepted.
        run_dir: Run directory for saving candidate files and artifacts.
            Required when candidates > 1.
        model_id: Gemini model for analysts and consolidator.
        max_workers: Max parallel analyst threads.
        agentic: Use agentic error analysts with tool access.
        candidates: Number of consolidation candidates (best-of-N).
            None = auto-decide based on meaningful_rate.
        max_chars: Max character count for evolved skill (default: 25000).
            Triggers compaction if exceeded to prevent skill bloat.

    Returns:
        Dict with evolved skill content, path, candidate paths, and
        summary statistics.
    """
    from agents.workflow.skill_evolution_agent.evolve import evolve

    skill_dir = _resolve_skill_dir(skill_dir)

    if not os.path.isfile(quality_report_path):
        return {"error": f"Quality report not found: {quality_report_path}"}

    skill_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_path):
        return {"error": f"SKILL.md not found in {skill_dir}"}

    candidates_dir = None
    if candidates is not None and candidates > 1:
        if not run_dir:
            return {"error": "run_dir is required when candidates > 1"}
        candidates_dir = os.path.join(run_dir, "candidates")
    elif candidates is None and run_dir:
        candidates_dir = os.path.join(run_dir, "candidates")

    try:
        # Read current skill for comparison
        with open(skill_path) as f:
            original_content = f.read()
        original_size = len(original_content)

        # Always snapshot the pre-evolution skill in run_dir
        if run_dir:
            import shutil
            os.makedirs(run_dir, exist_ok=True)
            agent_name = os.path.basename(os.path.dirname(skill_dir))
            pre_path = os.path.join(run_dir, f"pre_evolution_{agent_name}_skill.md")
            if not os.path.exists(pre_path):
                with open(pre_path, "w") as f:
                    f.write(original_content)
                logger.info("Saved pre-evolution snapshot: %s", pre_path)

        # Deterministic, incumbent-guarded candidate selection: score each
        # candidate on the eval set and keep the best only if it beats the V0
        # baseline. Falls back to size-based selection if no run dir is
        # available to score in.
        _score_fn = None
        _incumbent = None
        _score_dir = run_dir or candidates_dir
        if _score_dir:
            try:
                with open(quality_report_path) as _rf:
                    _incumbent = (
                        json.load(_rf).get("summary", {}).get("meaningful_rate")
                    )
            except Exception:  # noqa: BLE001
                _incumbent = None

            def _score_fn(skill_content, _sd=skill_dir, _rd=_score_dir):
                tmp = os.path.join(_rd, "_score_candidate_tmp.md")
                with open(tmp, "w") as fh:
                    fh.write(skill_content)
                res = score_candidate(
                    run_dir=_rd, candidate_path=tmp, skill_dir=_sd,
                    questions_file=_questions_file(),
                )
                return float(res.get("meaningful_rate", 0.0))

        evolved_content = evolve(
            report_path=quality_report_path,
            skill_dir=skill_dir,
            model_id=model_id,
            max_workers=max_workers,
            agentic=agentic,
            candidates=candidates,
            candidates_dir=candidates_dir,
            max_chars=max_chars,
            score_fn=_score_fn,
            incumbent_score=_incumbent,
        )

        # Write evolved skill (first candidate or single result)
        with open(skill_path, "w") as f:
            f.write(evolved_content)

        result = {
            "status": "success",
            "skill_path": skill_path,
            "original_size": original_size,
            "evolved_size": len(evolved_content),
            "growth": f"{len(evolved_content) - original_size:+d} chars",
        }

        # List candidate paths if best-of-N was used
        if candidates_dir and os.path.isdir(candidates_dir):
            cand_files = sorted([
                os.path.join(candidates_dir, f)
                for f in os.listdir(candidates_dir)
                if f.startswith("candidate_") and f.endswith(".md")
            ])
            result["candidate_paths"] = cand_files
            result["candidates_dir"] = candidates_dir
            result["note"] = (
                f"Generated {len(cand_files)} candidates. "
                "First candidate deployed to SKILL.md. "
                "Score each with score_candidate and pick the best."
            )

        return result

    except Exception as e:
        logger.error("Evolution failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Tool: detect_bottleneck_tool
# ---------------------------------------------------------------------------


def detect_bottleneck_tool(quality_report_path: str) -> dict:
    target_env = os.getenv("EVOLUTION_TARGET_AGENTS", "").strip()
    if target_env:
        # Target bound (--mode <agent>): classification would spend
        # ~5 min of LLM calls concluding what was already decided.
        return {
            "recommendation": target_env,
            "note": (
                f"Skipped classification: EVOLUTION_TARGET_AGENTS={target_env} "
                "binds the evolution target. Proceed directly to evolution."
            ),
        }
    """Detect which agent is the primary quality bottleneck.

    Classifies failures as routing, skill, tool, or architecture issues.
    Recommends which agent to evolve based on the agent registry.

    Args:
        quality_report_path: Path to quality report JSON file.

    Returns:
        Dict with recommendation (agent name, both, or none),
        failure counts, and confidence score.
    """
    from agents.workflow.skill_evolution_agent.bottleneck import detect_bottleneck

    if not os.path.isfile(quality_report_path):
        return {"error": f"Quality report not found: {quality_report_path}"}

    with open(quality_report_path) as f:
        report = json.load(f)

    client = genai.Client(
        vertexai=True,
        project=os.getenv("PROJECT_ID"),
        location=os.getenv("REGION", "us-central1"),
    )

    try:
        result = detect_bottleneck(report, client)
        return {
            "recommendation": result.recommendation,
            "confidence": result.confidence,
            "total_failures": result.total_failures,
            "routing_failures": len(result.routing_failures),
            "skill_failures": len(result.skill_failures),
            "tool_failures": len(result.tool_failures),
            "architecture_failures": len(result.architecture_failures),
            "summary": result.summary,
        }
    except Exception as e:
        logger.error("Bottleneck detection failed: %s", e, exc_info=True)
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Tool: run_coevolution
# ---------------------------------------------------------------------------


_coevolution_rounds_run = 0  # EVOLUTION_MAX_ROUNDS guard (per process)


def run_coevolution(
    quality_report_path: str,
    output_dir: str | None = None,
    model_id: str = "gemini-2.5-flash",
    max_workers: int = 10,
    agentic: bool = True,
) -> dict:
    """Run cross-agent co-evolution with automatic bottleneck detection.

    Detects which agent(s) need evolution and runs targeted evolution
    on the right agent(s). Agents are discovered from agent_registry.json.

    Args:
        quality_report_path: Path to quality report JSON file.
        output_dir: Directory to save evolved skills and logs.
        model_id: Gemini model for all LLM calls.
        max_workers: Max parallel threads.
        agentic: Use agentic error analysts with tool access.

    Returns:
        Dict with bottleneck recommendation, evolved agents, and timing.
    """
    from agents.workflow.skill_evolution_agent.coevolve import coevolve

    # EVOLUTION_MAX_ROUNDS (set by main.py from --rounds) is BINDING: the
    # orchestrating agent cannot add extra evolution rounds beyond it.
    global _coevolution_rounds_run
    max_rounds = os.getenv("EVOLUTION_MAX_ROUNDS")
    if max_rounds and _coevolution_rounds_run >= int(max_rounds):
        logger.warning(
            "run_coevolution refused: EVOLUTION_MAX_ROUNDS=%s reached "
            "(%d round(s) already run)", max_rounds, _coevolution_rounds_run,
        )
        return {
            "status": "refused",
            "reason": (
                f"EVOLUTION_MAX_ROUNDS={max_rounds} reached "
                f"({_coevolution_rounds_run} round(s) already run). "
                "Do NOT evolve further — publish the best result so far "
                "to the registry and open the PR."
            ),
        }
    _coevolution_rounds_run += 1

    if not os.path.isfile(quality_report_path):
        return {"error": f"Quality report not found: {quality_report_path}"}

    try:
        result = coevolve(
            report_path=quality_report_path,
            output_dir=output_dir,
            model_id=model_id,
            max_workers=max_workers,
            agentic=agentic,
            questions_file=_questions_file(),
            select_by_score=True,
        )

        deployed = {}
        for agent_name, agent_result in result.evolved_agents.items():
            if "error" in agent_result:
                continue
            evolved_path = None
            if output_dir:
                evolved_path = os.path.join(
                    output_dir, f"{agent_name}_evolved_skill.md",
                )
            if evolved_path and os.path.isfile(evolved_path):
                config = _AGENTS.get(agent_name, {})
                skill_dir = config.get("skill_dir", "")
                if skill_dir:
                    dst = os.path.join(skill_dir, "SKILL.md")
                    _safe_copy2(evolved_path, dst)
                    deployed[agent_name] = dst
                    logger.info("Deployed evolved %s skill to %s", agent_name, dst)

        return {
            "status": "success",
            "bottleneck_recommendation": result.bottleneck_recommendation,
            "bottleneck_summary": result.bottleneck_summary,
            "evolved_agents": result.evolved_agents,
            "deployed": deployed,
            "elapsed_seconds": result.elapsed_seconds,
            "summary": result.summary,
        }
    except Exception as e:
        logger.error("Co-evolution failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Tool: extract_eval_cases
# ---------------------------------------------------------------------------


def extract_eval_cases(quality_report_path: str, save: bool = True) -> dict:
    """Extract failed conversations as regression test eval cases.

    Reads a quality report, finds unhelpful and partial sessions, and
    formats them as eval case entries. Optionally saves them to
    eval/data/eval_cases.json.

    Args:
        quality_report_path: Path to quality report JSON file.
        save: If True, append extracted cases to eval_cases.json
            (deduplicating by id). If False, return cases without saving.

    Returns:
        Dict with extracted cases, counts, and save status.
    """
    from eval_cases import add_eval_cases, extract_regression_cases

    if not os.path.isfile(quality_report_path):
        return {"error": f"Quality report not found: {quality_report_path}"}

    with open(quality_report_path) as f:
        report = json.load(f)

    cases = extract_regression_cases(report)

    if not cases:
        return {
            "status": "no_failures",
            "extracted": 0,
            "message": "No unhelpful or partial sessions found.",
        }

    result = {
        "extracted": len(cases),
        "cases": cases,
    }

    if save:
        save_result = add_eval_cases(cases)
        result["save_status"] = save_result
        result["status"] = "saved"
    else:
        result["status"] = "extracted_only"

    return result


# ---------------------------------------------------------------------------
# Tool: read_eval_cases
# ---------------------------------------------------------------------------


def read_current_eval_cases() -> dict:
    """Read the current golden eval cases from eval/data/eval_cases.json.

    Use this to check what regression tests already exist before
    extracting new ones.

    Returns:
        The eval cases dict with eval_set_id, name, and eval_cases list.
    """
    from eval_cases import read_eval_cases

    return read_eval_cases()


# ---------------------------------------------------------------------------
# Tool: run_traffic
# ---------------------------------------------------------------------------

# Default questions file for evolution loop. Honor EVAL_QUESTIONS_FILE so the
# demo (e.g. run_demo.sh --quick) can validate candidates against the smaller
# quick set instead of the full 235-question set.
def _questions_file() -> str:
    """Resolve the scoring question set at CALL time, so bindings set by
    main.py (e.g. the --quick profile) reach the tools even though this
    module was imported earlier."""
    return os.environ.get("EVAL_QUESTIONS_FILE") or _QUESTIONS_FILE


_QUESTIONS_FILE = os.environ.get("EVAL_QUESTIONS_FILE") or os.path.join(
    _repo_root, "eval", "data", "questions", "demo_conversations.json"
)


def _safe_copy2(src: str, dst: str) -> None:
    """copy2 that no-ops when src and dst are the same file.

    A candidate skill can already be the deployed SKILL.md (e.g. evolution
    wrote it in place), in which case shutil.copy2 raises SameFileError.
    """
    import shutil
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    shutil.copy2(src, dst)


def _run_traffic(
    output_path: str,
    questions_file: str | None = None,
    concurrency: int = 10,
    max_turns: int = 4,
    local: bool = True,
) -> dict:
    """Run multi-turn traffic against the agent and save results.

    Generates synthetic multi-turn conversations by running questions
    from a file against the knowledge supervisor (local or deployed).

    Args:
        output_path: Path to save traffic JSON (e.g. /tmp/run/v0_traffic.json).
        questions_file: Path to questions JSON file. Defaults to the
            standard 205-question demo set.
        concurrency: Number of concurrent conversations (default: 10).
        max_turns: Max turns per conversation (default: 4).
        local: If True, run against local agent. If False, use deployed agent.

    Returns:
        Dict with status, output_path, number of conversations, and elapsed time.
    """
    if questions_file is None:
        questions_file = _QUESTIONS_FILE

    # Single env override so the whole evolve loop (candidate scoring, pre-flight)
    # can run single-turn. Multi-turn lets a follow-up recover a half-answered
    # compound question, masking the supervisor's decompose skill; max_turns=1
    # measures the single-shot skill the held-out report will grade.
    env_turns = os.environ.get("EVAL_MAX_TURNS")
    if env_turns:
        max_turns = int(env_turns)

    if not os.path.isfile(questions_file):
        return {"error": f"Questions file not found: {questions_file}"}

    out_dir = os.path.dirname(output_path)
    os.makedirs(out_dir, exist_ok=True)

    # Snapshot active skills alongside traffic results
    for name, config in _AGENTS.items():
        src = os.path.join(config["skill_dir"], "SKILL.md")
        if os.path.isfile(src):
            import shutil
            base = os.path.splitext(os.path.basename(output_path))[0]
            dst = os.path.join(out_dir, f"{base}_{name}_skill.md")
            if not os.path.exists(dst):
                shutil.copy2(src, dst)

    cmd = [
        sys.executable,
        os.path.join(_repo_root, "agents", "workflow", "traffic_generator", "main.py"),
        "--multi-turn",
        "--from-file", questions_file,
        "-o", output_path,
        "--concurrency", str(concurrency),
        "--max-turns", str(max_turns),
    ]
    if local:
        cmd.extend(["--local", "--local-agents"])

    logger.info("Running traffic: %s", " ".join(cmd))
    # Local validation traffic (candidate scoring, pre-flight fallback) must
    # NEVER land in the production analytics table: it would dilute the next
    # BigQuery-sourced quality report with evolved-candidate sessions that
    # carry the same agent_version. Removing the dataset env disables the
    # traffic generator's BigQuery plugin for this subprocess only.
    traffic_env = {
        k: v for k, v in os.environ.items()
        if not local or k not in ("DATASET_ID", "TABLE_ID", "DATASET_LOCATION")
    }
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, cwd=_repo_root, capture_output=True, text=True,
            timeout=7200,  # 2 hour timeout
            env=traffic_env,
        )
        elapsed = time.time() - t0

        if result.returncode != 0:
            # Include last 20 lines of stderr for diagnosis
            stderr_tail = "\n".join(result.stderr.strip().split("\n")[-20:])
            return {
                "status": "error",
                "returncode": result.returncode,
                "stderr_tail": stderr_tail,
                "elapsed_seconds": round(elapsed, 1),
            }

        # Count conversations in output
        n_conversations = 0
        if os.path.isfile(output_path):
            with open(output_path) as f:
                data = json.load(f)
            n_conversations = len(data) if isinstance(data, list) else 0

        return {
            "status": "success",
            "output_path": output_path,
            "conversations": n_conversations,
            "elapsed_seconds": round(elapsed, 1),
        }

    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Traffic generation timed out (2h limit)"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Tool: run_quality_report
# ---------------------------------------------------------------------------


def run_quality_report(
    results_path: str,
    output_path: str,
    concurrency: int = 10,
    tag_turns: bool = True,
    trajectory_samples: int | str = "all",
) -> dict:
    """Score traffic results with the two-phase scoring pipeline.

    Phase 1 (SDK scorer): Tags user turns (CORRECTION, VERIFY, etc.),
    identifies correction boundaries, and fetches execution traces
    from BigQuery.

    Uses the SDK scorer which handles ground truth, turn tagging,
    trajectory sampling, and structured quality scoring in a single pass.

    Args:
        results_path: Path to traffic results JSON (from run_traffic).
        output_path: Path to save final quality report JSON.
        concurrency: Number of concurrent judge calls (default: 10).
        tag_turns: Classify user turns and identify correction boundaries.
        trajectory_samples: Fetch N execution traces from BigQuery.

    Returns:
        Dict with status, summary metrics (meaningful_rate, unhelpful_rate),
        and the output path.
    """
    if not os.path.isfile(results_path):
        return {"error": f"Results file not found: {results_path}"}

    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()

    sdk_scorer = os.path.join(
        _repo_root, "eval", "scoring", "score_conversations.py",
    )
    cmd = [
        sys.executable, sdk_scorer,
        "-i", results_path,
        "-o", output_path,
        "--concurrency", str(concurrency),
        "--report",
    ]
    if tag_turns:
        cmd.append("--tag-turns")
    if trajectory_samples:
        traj_val = str(trajectory_samples)
        if traj_val != "0":
            cmd.extend(["--trajectory-samples", traj_val])
    _eval_spec = os.path.join(_repo_root, "eval", "data", "eval_spec.json")
    if os.path.isfile(_eval_spec):
        cmd.extend(["--eval-spec", _eval_spec])

    logger.info("SDK scorer: %s", " ".join(cmd))
    try:
        r = subprocess.run(
            cmd, cwd=_repo_root, capture_output=True, text=True,
            timeout=3600,
        )
        if r.returncode != 0:
            stderr_tail = "\n".join(r.stderr.strip().split("\n")[-20:])
            return {
                "status": "error",
                "phase": "sdk_scorer",
                "returncode": r.returncode,
                "stderr_tail": stderr_tail,
                "elapsed_seconds": round(time.time() - t0, 1),
            }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "SDK scorer timed out (1h limit)"}

    if not os.path.isfile(output_path):
        return {"status": "error", "error": "SDK scorer did not produce output"}

    with open(output_path) as f:
        report = json.load(f)

    summary = report.get("summary", {})
    return {
        "status": "success",
        "output_path": output_path,
        "meaningful_rate": summary.get("meaningful_rate"),
        "unhelpful_rate": summary.get("unhelpful_rate"),
        "total_sessions": summary.get("total_sessions"),
        "elapsed_seconds": round(time.time() - t0, 1),
    }


# ---------------------------------------------------------------------------
# Tool: upload_run_to_gcs
# ---------------------------------------------------------------------------


def upload_run_to_gcs(
    run_dir: str,
    bucket_name: str | None = None,
    prefix: str = "skill-evolution-runs",
) -> dict:
    """Upload a run directory to Google Cloud Storage.

    Uploads all files in the run directory to GCS for archival and
    sharing. Uses the run directory basename as the GCS subfolder.

    Controlled by the GCS_UPLOAD env var (default: false). When false,
    upload is skipped. GCS_BUCKET must always be configured in .env.

    Args:
        run_dir: Local path to the run directory.
        bucket_name: GCS bucket name. Defaults to the GCS_BUCKET env var.
        prefix: GCS path prefix (default: 'skill-evolution-runs').

    Returns:
        Dict with status, GCS URI, and number of files uploaded.
        Returns status="skipped" if GCS_UPLOAD is not enabled.
    """
    from agents.workflow.gcs_utils import upload_dir_to_gcs

    return upload_dir_to_gcs(run_dir, bucket_name=bucket_name, prefix=prefix)


def download_from_gcs(gcs_uri: str, local_path: str) -> dict:
    """Download a file from GCS to local filesystem.

    Args:
        gcs_uri: GCS URI (gs://bucket/path/to/file).
        local_path: Local path to save the file.

    Returns:
        Dict with status and local_path.
    """
    from agents.workflow.gcs_utils import download_from_gcs as _download

    return _download(gcs_uri, local_path)


# ---------------------------------------------------------------------------
# PR creation helpers
# ---------------------------------------------------------------------------


def _find_agy() -> str | None:
    """Find the agy CLI binary."""
    import shutil
    path = shutil.which("agy")
    if path:
        return path
    candidates = [
        os.path.expanduser("~/.local/bin/agy"),
        "/usr/local/bin/agy",
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _generate_pr_body_with_agy(
    agent: str, version: str, metrics: dict, evolved_size: int,
    run_dir: str, diff_text: str,
) -> str | None:
    """Use agy to generate a rich PR description from the diff."""
    agy_bin = _find_agy()
    if not agy_bin:
        return None

    prompt = (
        f"Write a pull request description for the following change.\n"
        f"Agent: {agent}, version: {version}\n"
        f"Quality: meaningful rate {metrics['baseline_meaningful']}% "
        f"-> {metrics['evolved_meaningful']}%, "
        f"unhelpful rate {metrics['baseline_unhelpful']}% "
        f"-> {metrics['evolved_unhelpful']}%\n"
        f"Skill size: {evolved_size} chars, "
        f"run: {os.path.basename(run_dir)}\n\n"
        f"Diff:\n{diff_text[:3000]}\n\n"
        f"Output ONLY the PR body in markdown. Include a quality metrics "
        f"table and a summary of what changed in the skill. No preamble."
    )

    try:
        result = subprocess.run(
            [agy_bin, "-p", prompt],
            cwd=_repo_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        logger.warning("agy PR body generation failed: %s", e)
    return None


def _default_pr_body(
    agent: str, version: str, metrics: dict,
    evolved_size: int, run_dir: str,
    session_ids: list[str] | None = None,
) -> str:
    """Fallback PR body when agy is not available."""
    m = metrics
    body = (
        f"## Skill Evolution: {agent} {version}\n\n"
        f"### Quality Before Evolution\n\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"| Meaningful rate | {m['baseline_meaningful']}% |\n"
        f"| Unhelpful rate | {m['baseline_unhelpful']}% |\n\n"
        f"### Candidate Eval Scores\n\n"
        f"| Metric | Baseline ({m['baseline_label']}) "
        f"| Evolved ({version}) |\n"
        f"|--------|:------------:|:-------------------:|\n"
        f"| Meaningful rate | {m['baseline_meaningful']}% "
        f"| {m['evolved_meaningful']}% |\n"
        f"| Unhelpful rate | {m['baseline_unhelpful']}% "
        f"| {m['evolved_unhelpful']}% |\n"
        f"| Skill size | | {evolved_size} chars |\n\n"
    )
    selector_path = os.path.join(run_dir, "trace_selector.json")
    if os.path.isfile(selector_path):
        try:
            with open(selector_path) as f:
                sel = json.load(f)
            labels = ", ".join(f"{k}={v}" for k, v in (sel.get("labels") or {}).items()) or "(none)"
            body += (
                f"### Trace Selector (reproducibility)\n\n"
                f"Evolved from BigQuery traces where: app=`{sel.get('app_name')}`, "
                f"agent_version=`{sel.get('agent_version') or 'any'}`, "
                f"labels: {labels}, window: {sel.get('time_period')}\n\n"
            )
        except Exception:
            pass
    if session_ids:
        body += f"### Failing Sessions ({len(session_ids)})\n\n"
        for sid in session_ids[:10]:
            body += f"- `{sid}`\n"
        if len(session_ids) > 10:
            body += f"- ... and {len(session_ids) - 10} more\n"
        body += "\n"
    body += f"Run: `{os.path.basename(run_dir)}`\n"
    return body


# ---------------------------------------------------------------------------
# Tool: create_evolution_pr
# ---------------------------------------------------------------------------


def _extract_rate(report_path: str, field: str) -> str:
    if not report_path or not os.path.isfile(report_path):
        return "?"
    try:
        with open(report_path) as f:
            data = json.load(f)
        val = data["summary"][field]
        return f"{round(val, 1)}"
    except Exception:
        return "?"


def _find_evolved_skill(run_dir: str, version: str, agent: str) -> str | None:
    """Find the evolved skill MD file in the run directory."""
    candidates = [
        f"best_{version}_skill.md",
        f"{version}_{agent}_skill.md",
        f"{version}_skill.md",
    ]
    for name in candidates:
        path = os.path.join(run_dir, name)
        if os.path.isfile(path):
            return path
    return None


def _resolve_repo_skill_path(agent: str) -> str | None:
    """Resolve the in-repo path for an agent's SKILL.md from the registry."""
    if agent not in _AGENTS:
        return None
    skill_dir = _AGENTS[agent]["skill_dir"]
    return os.path.relpath(os.path.join(skill_dir, "SKILL.md"), _repo_root)


def _collect_quality_metrics(
    run_dir: str, version: str,
) -> dict:
    """Collect baseline and evolved quality metrics from report files."""
    import glob as glob_mod

    evolved_report = None
    for name in [
        f"{version}_quality_report.json",
        f"best_{version}_quality_report.json",
    ]:
        path = os.path.join(run_dir, name)
        if os.path.isfile(path):
            evolved_report = path
            break

    if evolved_report is None:
        # Co-evolution runs score best-of-N candidates without writing a
        # {version}_quality_report.json — fall back to the best candidate
        # report so PR titles carry the real evolved rate instead of "?%".
        best_rate = -1.0
        for pattern in ("candidate_*_report.json",
                        "_score_candidate_*_report.json"):
            for path in glob_mod.glob(
                os.path.join(run_dir, "**", pattern), recursive=True,
            ):
                try:
                    rate = float(_extract_rate(path, "meaningful_rate"))
                except ValueError:
                    continue
                if rate > best_rate:
                    best_rate, evolved_report = rate, path

    baseline_report = None
    baseline_label = "initial"
    baseline_candidates = sorted(glob_mod.glob(
        os.path.join(run_dir, "*_quality_report.json")
    ))
    if baseline_candidates:
        baseline_report = baseline_candidates[0]
        baseline_label = os.path.basename(
            baseline_report
        ).split("_quality_report")[0]

    return {
        "evolved_meaningful": _extract_rate(evolved_report, "meaningful_rate"),
        "evolved_unhelpful": _extract_rate(evolved_report, "unhelpful_rate"),
        "baseline_meaningful": _extract_rate(baseline_report, "meaningful_rate"),
        "baseline_unhelpful": _extract_rate(baseline_report, "unhelpful_rate"),
        "baseline_label": baseline_label,
    }



def _gather_run_context(run_dir: str, version: str, agent: str) -> str:
    """Gather all available context from a run directory for agy prompts."""
    import glob as glob_mod
    parts = []

    # Summary.json — version comparison table
    summary_path = os.path.join(run_dir, "summary.json")
    if os.path.isfile(summary_path):
        with open(summary_path) as f:
            summary = json.load(f)
        parts.append("## Version Comparison\n")
        parts.append("| Version | Sessions | Meaningful | Unhelpful | Tool Usage | Specificity | First-Time-Right |")
        parts.append("|---------|----------|------------|-----------|------------|-------------|------------------|")
        for v_label, v_data in summary.items():
            dims = v_data.get("dimension_averages", {})
            parts.append(
                f"| {v_label} | {v_data.get('total_sessions', '?')} "
                f"| {v_data.get('meaningful_rate', '?')}% "
                f"| {v_data.get('unhelpful_rate', '?')}% "
                f"| {dims.get('tool_usage', '?')} "
                f"| {dims.get('specificity', '?')} "
                f"| {dims.get('first_time_right', '?')} |"
            )
        parts.append("")

    # Pre-evolution skill (what we started from)
    pre_skill = os.path.join(run_dir, f"pre_evolution_{agent}_skill.md")
    if not os.path.isfile(pre_skill):
        pre_skill = os.path.join(run_dir, f"v0_{agent.split('_')[0]}_skill.md")
    if os.path.isfile(pre_skill):
        with open(pre_skill) as f:
            content = f.read()
        parts.append(f"## Pre-Evolution Skill ({len(content)} chars)\n")
        parts.append(f"```markdown\n{content[:2000]}\n```\n")

    # Evolved skill
    evolved_path = _find_evolved_skill(run_dir, version, agent)
    if evolved_path:
        with open(evolved_path) as f:
            content = f.read()
        parts.append(f"## Evolved Skill {version} ({len(content)} chars)\n")
        parts.append(f"```markdown\n{content[:3000]}\n```\n")

    # Candidate scores (if best-of-N was used)
    candidate_reports = sorted(glob_mod.glob(
        os.path.join(run_dir, "candidate_*_report.json")
    ))
    if candidate_reports:
        parts.append("## Candidate Scores (Best-of-N)\n")
        parts.append("| Candidate | Meaningful | Unhelpful | Sessions |")
        parts.append("|-----------|------------|-----------|----------|")
        for rpath in candidate_reports:
            cname = os.path.basename(rpath).split("_report")[0]
            try:
                with open(rpath) as f:
                    cdata = json.load(f)
                cs = cdata.get("summary", {})
                parts.append(
                    f"| {cname} | {cs.get('meaningful_rate', '?')}% "
                    f"| {cs.get('unhelpful_rate', '?')}% "
                    f"| {cs.get('total_sessions', '?')} |"
                )
            except Exception:
                pass
        parts.append("")

    # Sample failures from baseline report
    baseline_reports = sorted(glob_mod.glob(
        os.path.join(run_dir, "*_quality_report.json")
    ))
    if baseline_reports:
        try:
            with open(baseline_reports[0]) as f:
                report = json.load(f)
            sessions = report.get("sessions", [])
            failures = [
                s for s in sessions
                if s.get("metrics", {}).get("response_usefulness", {}).get("category") == "unhelpful"
            ][:5]
            if failures:
                parts.append("## Sample Failures (from baseline)\n")
                for s in failures:
                    q = s.get("question", "?")
                    reason = s.get("metrics", {}).get(
                        "response_usefulness", {}
                    ).get("justification", "")[:200]
                    parts.append(f"- **Q:** {q}")
                    parts.append(f"  **Why unhelpful:** {reason}\n")
        except Exception:
            pass

    return "\n".join(parts)


def parse_quality_issue(issue_number: int) -> dict:
    """Read a quality issue from GitHub and extract structured context.

    Parses the structured markdown body created by the Quality Agent,
    extracting the metadata table, root cause, failure patterns,
    affected sessions, and recommended fix.

    Args:
        issue_number: GitHub issue number to read.

    Returns:
        Dict with category, agent_name, topic, severity, root_cause,
        failure_patterns, recommendation, affected_questions,
        quality_summary, and the full issue body.
    """
    import re

    r = subprocess.run(
        ["gh", "issue", "view", str(issue_number),
         "--json", "title,body,labels,state"],
        cwd=_repo_root, capture_output=True, text=True,
    )
    if r.returncode != 0:
        return {"error": f"Failed to read issue #{issue_number}: {r.stderr}"}

    data = json.loads(r.stdout)
    body = data.get("body", "")
    labels = [l["name"] for l in data.get("labels", [])]
    title = data.get("title", "")

    result = {
        "issue_number": issue_number,
        "title": title,
        "state": data.get("state", ""),
        "labels": labels,
        "body": body,
    }

    # Parse metadata table: | Field | Value |
    metadata = {}
    for m in re.finditer(
        r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$", body, re.MULTILINE,
    ):
        key = m.group(1).strip().strip("*").lower()
        val = m.group(2).strip().strip("`")
        if key in ("field", "value") or key.startswith("-") or key.startswith(":"):
            continue
        metadata[key] = val

    result["category"] = metadata.get("category", "")
    result["agent_name"] = metadata.get("agent", "")
    result["topic"] = metadata.get("topic", "")
    result["severity"] = metadata.get("severity", "")
    result["action_needed"] = metadata.get("action needed", "")
    result["sessions_affected"] = metadata.get("sessions affected", "")
    result["meaningful_rate"] = metadata.get("meaningful rate", "")

    # Extract root cause section
    root_match = re.search(
        r"## Root Cause\s*\n+(.+?)(?=\n## |\Z)", body, re.DOTALL,
    )
    result["root_cause"] = root_match.group(1).strip() if root_match else ""

    # Extract failure patterns table
    patterns = []
    pat_section = re.search(
        r"## Failure Patterns\s*\n+(.+?)(?=\n## |\Z)", body, re.DOTALL,
    )
    if pat_section:
        for row in re.finditer(
            r"^\|\s*(.+?)\s*\|\s*(\d+)\s*\|\s*(\w+)\s*\|\s*(.+?)\s*\|$",
            pat_section.group(1), re.MULTILINE,
        ):
            pat = row.group(1).strip()
            if pat.lower() in ("pattern", "---"):
                continue
            patterns.append({
                "pattern": pat,
                "count": int(row.group(2)),
                "verdict": row.group(3).strip(),
                "example_question": row.group(4).strip(),
            })
    result["failure_patterns"] = patterns

    # Extract recommended fix
    rec_match = re.search(
        r"## Recommended Fix\s*\n+(.+?)(?=\n## |\n---|\Z)", body, re.DOTALL,
    )
    result["recommendation"] = rec_match.group(1).strip() if rec_match else ""

    # Extract affected session IDs and questions
    questions = []
    session_ids = []
    sessions_section = re.search(
        r"<details>.*?</details>", body, re.DOTALL,
    )
    if sessions_section:
        for sid_match in re.finditer(
            r"### Session \d+: `(.+?)`", sessions_section.group(0),
        ):
            session_ids.append(sid_match.group(1))
        for q_match in re.finditer(
            r"\*\*Question:\*\*\s*(.+)", sessions_section.group(0),
        ):
            questions.append(q_match.group(1).strip())
    result["session_ids"] = session_ids
    result["affected_questions"] = questions

    # Extract reproduce commands
    reproduce_match = re.search(
        r"## Reproduce\s*\n+```(?:bash)?\s*\n(.+?)```",
        body, re.DOTALL,
    )
    if reproduce_match:
        cmds = reproduce_match.group(1).strip().split("\n")
        smoke_questions = []
        for cmd in cmds:
            q_in_cmd = re.search(r'"(.+?)"', cmd)
            if q_in_cmd:
                smoke_questions.append(q_in_cmd.group(1))
        if smoke_questions:
            result["affected_questions"] = list(
                set(result["affected_questions"] + smoke_questions)
            )

    # Quality report summary
    summary = {}
    sum_section = re.search(
        r"## Quality Report Summary\s*\n+(.+?)(?=\n---|\n\*|\Z)",
        body, re.DOTALL,
    )
    if sum_section:
        for row in re.finditer(
            r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$",
            sum_section.group(1), re.MULTILINE,
        ):
            k = row.group(1).strip().lower()
            v = row.group(2).strip().strip("`")
            if k not in ("metric", "value") and not k.startswith("-"):
                summary[k] = v
    result["quality_summary"] = summary

    return result


def create_evolution_issue(
    run_dir: str,
    version: str = "v1",
    agent: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Create a GitHub issue documenting the skill evolution run.

    Gathers quality metrics, version comparisons, candidate scores,
    skill diffs, and sample failures from the run directory, then uses
    ``agy`` to generate a rich issue body. Falls back to a structured
    template if agy is unavailable.

    Args:
        run_dir: Path to the run directory with evolution artifacts.
        version: Evolved skill version label (e.g. 'v1', 'v2').
        agent: Agent that was evolved (name from agent_registry.json).
            Defaults to first agent in registry if not specified.
        dry_run: If True, write issue to local file instead of GitHub.

    Returns:
        Dict with status, issue URL/number, or dry_run file path.
    """
    if agent is None:
        agent = _DEFAULT_AGENT
    run_dir = os.path.abspath(run_dir)
    if not os.path.isdir(run_dir):
        return {"error": f"Run directory not found: {run_dir}"}

    metrics = _collect_quality_metrics(run_dir, version)
    run_context = _gather_run_context(run_dir, version, agent)

    evolved_path = _find_evolved_skill(run_dir, version, agent)
    evolved_size = 0
    if evolved_path:
        evolved_size = os.path.getsize(evolved_path)

    meaningful = metrics["evolved_meaningful"]
    baseline = metrics["baseline_meaningful"]
    title = (
        f"[Evolution] {agent} skill {version} — "
        f"meaningful {baseline}% → {meaningful}%"
    )

    agy_prompt = (
        f"Write a GitHub issue body for the following skill evolution run.\n\n"
        f"Title: {title}\n"
        f"Agent: {agent}\n"
        f"Version: {version}\n"
        f"Run directory: {os.path.basename(run_dir)}\n"
        f"Evolved skill size: {evolved_size} chars\n\n"
        f"Context from the run:\n\n{run_context}\n\n"
        f"Write the issue body in markdown with these sections:\n"
        f"1. **Metadata** — a table with: agent, version, meaningful rate "
        f"(baseline → evolved), unhelpful rate, skill size, run directory, "
        f"labels\n"
        f"2. **Quality Impact** — summarize what improved and by how much, "
        f"including dimension-level changes (tool_usage, specificity, "
        f"first_time_right) if available\n"
        f"3. **What Changed in the Skill** — describe the key changes "
        f"in the evolved skill compared to the baseline (new sections, "
        f"keyword mappings, anti-patterns, etc.)\n"
        f"4. **Candidate Selection** — if best-of-N candidates were "
        f"evaluated, show their scores and explain which was selected\n"
        f"5. **Remaining Failures** — list sample questions that still "
        f"fail after evolution, if any\n"
        f"6. **Verification** — how to verify: deploy the evolved skill "
        f"and run traffic\n\n"
        f"Output ONLY the issue body markdown. No preamble or explanation."
    )

    # Try agy, fall back to template
    agy_bin = _find_agy()
    issue_body = None
    if agy_bin:
        try:
            result = subprocess.run(
                [agy_bin, "-p", agy_prompt],
                cwd=_repo_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0 and result.stdout.strip():
                issue_body = result.stdout.strip()
        except Exception as e:
            logger.warning("agy issue generation failed: %s", e)

    if not issue_body:
        m = metrics
        issue_body = (
            f"## Metadata\n\n"
            f"| Field | Value |\n"
            f"|-------|-------|\n"
            f"| Agent | `{agent}` |\n"
            f"| Version | `{version}` |\n"
            f"| Meaningful rate | {m['baseline_meaningful']}% → "
            f"{m['evolved_meaningful']}% |\n"
            f"| Unhelpful rate | {m['baseline_unhelpful']}% → "
            f"{m['evolved_unhelpful']}% |\n"
            f"| Skill size | {evolved_size} chars |\n"
            f"| Run | `{os.path.basename(run_dir)}` |\n\n"
            f"## Run Context\n\n{run_context}\n"
        )

    labels = ["evolution", agent]

    if dry_run:
        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"issue_evolution_{agent}_{version}_{ts}.md"
        filepath = os.path.join(run_dir, filename)
        with open(filepath, "w") as f:
            f.write(f"# {title}\n\n")
            f.write(f"**Labels:** {', '.join(labels)}\n\n")
            f.write(issue_body + "\n")
        return {"status": "dry_run", "file": filepath, "title": title}

    # Create issue via gh CLI
    try:
        label_args = []
        for label in labels:
            label_args.extend(["--label", label])

        r = subprocess.run(
            ["gh", "issue", "create",
             "--title", title,
             "--body", issue_body,
             *label_args],
            cwd=_repo_root,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            # Labels may not exist yet — retry without labels
            logger.warning("gh issue create failed with labels: %s", r.stderr)
            r = subprocess.run(
                ["gh", "issue", "create",
                 "--title", title,
                 "--body", issue_body],
                cwd=_repo_root,
                capture_output=True,
                text=True,
            )
        if r.returncode != 0:
            return {"status": "error", "error": r.stderr}

        issue_url = r.stdout.strip()
        # Extract issue number from URL
        issue_number = issue_url.rstrip("/").split("/")[-1]
        logger.info("Created issue #%s: %s", issue_number, issue_url)

        # Save issue as .md in run directory
        md_path = os.path.join(
            run_dir, f"issue_{issue_number}_evolution.md",
        )
        with open(md_path, "w") as f:
            f.write(f"# {title}\n\n")
            f.write(f"**Issue:** {issue_url}\n")
            f.write(f"**Labels:** {', '.join(labels)}\n\n")
            f.write(issue_body + "\n")
        logger.info("Saved issue .md to %s", md_path)

        return {
            "status": "created",
            "url": issue_url,
            "number": int(issue_number),
            "title": title,
            "md_path": md_path,
        }

    except Exception as e:
        logger.error("Failed to create issue: %s", e)
        return {"status": "error", "error": str(e)}


def _ensure_git_workdir() -> str:
    """Return a git workdir for PR creation.

    Locally this is the repo checkout (_repo_root). Deployed containers run
    from an image where /app is not a git repository, so clone the target
    repo (GITHUB_REPO) with GH_TOKEN into a fresh temp dir at
    GITHUB_BASE_BRANCH and configure a commit identity there.
    """
    import tempfile

    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=_repo_root, capture_output=True, text=True,
    )
    if r.returncode == 0:
        return _repo_root

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    if not token or not repo:
        raise RuntimeError(
            "Not a git checkout and GH_TOKEN/GITHUB_REPO are not set — "
            "cannot create a PR workdir. Set both on the Cloud Run Job."
        )
    base_branch = os.environ.get("GITHUB_BASE_BRANCH", "main")
    workdir = tempfile.mkdtemp(prefix="evolution_pr_")
    clone_url = f"https://x-access-token:{token}@github.com/{repo}.git"
    r = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", base_branch,
         clone_url, workdir],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        # Never echo stderr verbatim upstream of this point without masking:
        # the clone URL embeds the token.
        raise RuntimeError(
            f"Clone of {repo}@{base_branch} failed: "
            f"{r.stderr.replace(token, '***')[-500:]}"
        )
    subprocess.run(
        ["git", "config", "user.name",
         os.environ.get("GIT_USER_NAME", "skill-evolution-agent")],
        cwd=workdir, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email",
         os.environ.get("GIT_USER_EMAIL",
                        "skill-evolution-agent@users.noreply.github.com")],
        cwd=workdir, capture_output=True,
    )
    logger.info("PR workdir: fresh clone of %s at %s", repo, workdir)
    return workdir


def push_skill_to_registry(
    run_dir: str,
    version: str = "v1",
    agent: str | None = None,
) -> dict:
    """Push an evolved skill to the Agent Platform Skill Registry.

    Creates a new immutable revision for the agent's ``skill_id`` (from
    agent_registry.json). Deployed agents running with SKILL_SOURCE=registry
    serve the new revision after their next restart/redeploy. Call this ONLY
    after the evolved skill passed the quality gate.

    Args:
        run_dir: Run directory containing the evolved skill file.
        version: Skill version label (e.g. 'v1', 'v2').
        agent: Agent name from agent_registry.json.

    Returns:
        Dict with status, skill_id and revision count.
    """
    import shutil
    import tempfile

    if agent is None:
        agent = _DEFAULT_AGENT
    entry = _AGENTS.get(agent)
    if not entry:
        return {"status": "error", "error": f"Unknown agent: {agent}"}
    skill_id = entry.get("skill_id")
    if not skill_id:
        return {
            "status": "skipped",
            "reason": f"No skill_id for '{agent}' in agent_registry.json",
        }
    run_dir = os.path.abspath(run_dir)
    evolved_skill_path = _find_evolved_skill(run_dir, version, agent)
    if not evolved_skill_path:
        return {
            "status": "error",
            "error": f"No evolved skill found in {run_dir} for {version}",
        }

    from agents.enterprise.policy_agent.skill_loader import _skill_registry_class

    # Stage evolved SKILL.md + the agent's reference files as the revision.
    staging = tempfile.mkdtemp(prefix=f"registry_push_{agent}_")
    try:
        shutil.copy2(evolved_skill_path, os.path.join(staging, "SKILL.md"))
        refs_dir = os.path.join(entry["skill_dir"], "references")
        if os.path.isdir(refs_dir):
            shutil.copytree(refs_dir, os.path.join(staging, "references"))
        project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("PROJECT_ID")
        if not project:
            return {"status": "error", "error": "PROJECT_ID not set"}
        location = _REGISTRY.get("registry_location", "us-central1")
        client = _skill_registry_class()(project, location)
        if client.exists(skill_id):
            client.update(skill_id, staging, description=entry.get("label", agent))
        else:
            client.create(skill_id, staging, description=entry.get("label", agent))
        revisions = client.list_revisions(skill_id)
        logger.info(
            "Pushed %s %s to registry %s (revisions now: %d)",
            agent, version, skill_id, len(revisions),
        )
        return {
            "status": "pushed",
            "skill_id": skill_id,
            "revisions": len(revisions),
            "skill_file": evolved_skill_path,
        }
    except Exception as e:
        logger.error("Registry push failed: %s", e)
        return {"status": "error", "error": str(e)}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def extract_regression_cases(
    run_dir: str,
    agent: str = "policy_agent",
    max_cases: int = 5,
) -> dict:
    """Extract RESOLVED failures into the golden regression gate.

    A resolved failure is a question the baseline quality report scored
    unhelpful/partial but the WINNING candidate's report scored
    meaningful. Each becomes:
      - an eval/data/eval_cases.json entry (CI routing gate;
        expected_agent from the question's category), and
      - an eval/data/golden_evals.json entry (LLM-judge ground truth;
        the winning candidate's judge-approved answer).

    The gate grows each evolution cycle, so a future skill that
    re-breaks a resolved case fails CI before it can merge. Call this
    AFTER candidate selection and BEFORE create_evolution_pr — the PR
    picks up the updated eval files automatically.
    """
    import glob as glob_mod

    def _usefulness(session: dict) -> str:
        return (
            (session.get("metrics") or {})
            .get("response_usefulness", {})
            .get("category", "")
        )

    # Baseline report = earliest *_quality_report.json in the run dir
    reports = sorted(glob_mod.glob(
        os.path.join(run_dir, "*_quality_report.json")
    ))
    if not reports:
        # Clean skip (an "error" makes the orchestrator retry in a loop)
        return {"status": "skipped",
                "reason": f"No baseline quality report in {run_dir}"}
    with open(reports[0]) as f:
        baseline = json.load(f)
    failures = {
        s["question"]: s for s in baseline.get("sessions", [])
        if _usefulness(s) in ("unhelpful", "partial") and s.get("question")
    }
    if not failures:
        return {"status": "no_failures", "added": 0}

    # Winning candidate = highest meaningful_rate candidate report
    best_report, best_rate = None, -1.0
    # Two naming schemes: the orchestrator scoring calls
    # (candidate_N_report.json) and coevolve internal scoring
    # (_score_candidate_N_report.json).
    patterns = ["candidate_*_report.json", "_score_candidate_*_report.json"]
    for pattern in patterns:
        for p in glob_mod.glob(
            os.path.join(run_dir, "**", pattern), recursive=True,
        ):
            try:
                rate = float(_extract_rate(p, "meaningful_rate"))
            except ValueError:
                continue
            if rate > best_rate:
                best_rate, best_report = rate, p
    if not best_report:
        return {"status": "skipped",
                "reason": f"No candidate reports in {run_dir}"}
    with open(best_report) as f:
        winner = json.load(f)
    resolved = []
    for s in winner.get("sessions", []):
        q = s.get("question", "")
        if q in failures and _usefulness(s) == "meaningful" and s.get("response"):
            resolved.append(s)
    if not resolved:
        return {"status": "no_resolved_failures", "added": 0}

    # question -> category from the shipped question sets (deterministic)
    q_category = {}
    for qf in glob_mod.glob(
        os.path.join(_repo_root, "eval", "data", "questions", "*.json")
    ):
        try:
            with open(qf) as f:
                qdata = json.load(f)
            for item in qdata.get("questions", qdata if isinstance(qdata, list) else []):
                if isinstance(item, dict) and item.get("question"):
                    q_category[item["question"]] = item.get("category", "")
        except Exception:
            continue
    agent_for_category = {"benefits": "benefits_agent", "calc": "hr_calculator"}

    eval_cases_path = os.path.join(_repo_root, "eval", "data", "eval_cases.json")
    golden_path = os.path.join(_repo_root, "eval", "data", "golden_evals.json")
    new_eval_cases, new_golden = [], []
    stamp = time.strftime("%Y%m%d")
    for i, s in enumerate(resolved[:max_cases], 1):
        q = s["question"]
        category = q_category.get(q, "")
        answer = " ".join(s["response"].split())
        if len(answer) > 400:
            answer = answer[:400].rsplit(". ", 1)[0] + "."
        case_id = f"reg-{stamp}-{i:02d}"
        new_eval_cases.append({
            "id": case_id,
            "question": q,
            "category": category or "regression",
            "expected_agent": agent_for_category.get(category, "policy_agent"),
        })
        new_golden.append({
            "id": case_id,
            "question": q,
            "expected_answer": answer,
            "topic": category or "regression",
        })

    added_eval = _append_regression_cases(eval_cases_path, new_eval_cases)
    added_golden = _append_regression_cases(golden_path, new_golden)

    marker = {
        "added_eval_cases": added_eval,
        "added_golden": added_golden,
        "source_baseline": os.path.basename(reports[0]),
        "source_candidate": os.path.basename(best_report),
        "cases": [c["question"] for c in new_eval_cases[:added_eval]] if added_eval else [],
    }
    with open(os.path.join(run_dir, "regression_cases.json"), "w") as f:
        json.dump(marker, f, indent=2)

    logger.info(
        "Extracted %d regression case(s) from %d resolved failure(s) "
        "(gate grows: eval_cases +%d, golden +%d)",
        added_eval, len(resolved), added_eval, added_golden,
    )
    return {"status": "success", **marker}


def _append_regression_cases(path: str, new_cases: list[dict]) -> int:
    """Append cases with id+question dedup. Handles both file shapes
    ({"eval_cases": [...]} and bare list)."""
    with open(path) as f:
        data = json.load(f)
    cases = data["eval_cases"] if isinstance(data, dict) else data
    existing_ids = {c.get("id") for c in cases}
    existing_questions = {c.get("question") for c in cases}
    added = 0
    for case in new_cases:
        if case["id"] in existing_ids or case["question"] in existing_questions:
            continue
        cases.append(case)
        existing_ids.add(case["id"])
        existing_questions.add(case["question"])
        added += 1
    if added:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    return added


def create_evolution_pr(
    run_dir: str,
    version: str = "v1",
    agent: str | None = None,
    base_branch: str = os.environ.get("GITHUB_BASE_BRANCH", "main"),
    dry_run: bool = False,
    output_file: str | None = None,
    issue_number: int | None = None,
    session_ids: list[str] | None = None,
) -> dict:
    """Create a GitHub PR with the evolved skill.

    Uses deterministic git commands for branch/commit/push (only the
    SKILL.md file), then ``gh pr create`` for the PR. If ``agy``
    (Antigravity CLI) is available, uses it to generate a richer PR
    description from the diff; otherwise falls back to a metrics table.

    When ``output_file`` is set, writes the evolved skill to that path
    instead of creating a PR.

    Args:
        run_dir: Path to the run directory containing evolved skills
            and quality reports.
        version: Skill version label (e.g. 'v1', 'v2').
        agent: Agent to create PR for (name from agent_registry.json).
        base_branch: Base branch for the PR. Env: GITHUB_BASE_BRANCH.
        dry_run: If True, preview branch/title/body without creating.
        output_file: If set, write the evolved skill to this path and
            skip PR creation entirely.
        issue_number: If set, append 'Fixes #N' to the PR body to
            auto-close the linked issue on merge.
        session_ids: Failing session IDs from the quality issue, included
            in the PR body for traceability.

    Returns:
        Dict with status, PR URL, and metrics.
    """
    if agent is None:
        agent = _DEFAULT_AGENT
    run_dir = os.path.abspath(run_dir)
    if not os.path.isdir(run_dir):
        return {"error": f"Run directory not found: {run_dir}"}

    # --- Locate evolved skill ---
    evolved_skill_path = _find_evolved_skill(run_dir, version, agent)
    if not evolved_skill_path:
        return {
            "error": f"No evolved skill found in {run_dir} for {version}",
        }

    with open(evolved_skill_path) as f:
        evolved_content = f.read()

    # --- Resolve skill path in the repo ---
    repo_skill_path = _resolve_repo_skill_path(agent)
    if not repo_skill_path:
        return {
            "error": f"Agent '{agent}' not found in agent registry. "
                     f"Available: {', '.join(sorted(_AGENTS.keys()))}",
        }

    # --- Output-file mode: write locally and return ---
    if output_file:
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
        with open(output_file, "w") as f:
            f.write(evolved_content)
        return {
            "status": "written",
            "output_file": output_file,
            "size": len(evolved_content),
        }

    # --- Collect quality metrics ---
    metrics = _collect_quality_metrics(run_dir, version)
    evolved_size = len(evolved_content)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    branch_name = f"skill-evolution/{agent}-{version}-{timestamp}"
    title = (
        f"Evolve {agent} skill to {version} "
        f"({metrics['baseline_meaningful']}% "
        f"-> {metrics['evolved_meaningful']}%)"
    )

    if dry_run:
        body = _default_pr_body(
            agent, version, metrics, evolved_size, run_dir, session_ids,
        )
        return {
            "status": "dry_run",
            "title": title,
            "branch": branch_name,
            "base_branch": base_branch,
            "repo_skill_path": repo_skill_path,
            "evolved_skill_size": evolved_size,
            "metrics": metrics,
            "body_preview": body,
        }

    # --- Resolve a git workdir (deployed containers are not a checkout) ---
    try:
        git_root = _ensure_git_workdir()
    except RuntimeError as e:
        return {"status": "error", "error": str(e)}

    # --- Remember current branch to restore later ---
    try:
        original_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=git_root, capture_output=True, text=True,
        ).stdout.strip()
    except Exception:
        original_branch = base_branch

    # --- Stash uncommitted changes ---
    stashed = False
    dirty = subprocess.run(
        ["git", "diff", "--quiet"], cwd=git_root,
    ).returncode != 0
    cached = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=git_root,
    ).returncode != 0
    if dirty or cached:
        subprocess.run(
            ["git", "stash", "push", "-m", "create_evolution_pr: temp stash"],
            cwd=git_root, capture_output=True,
        )
        stashed = True

    try:
        # --- Create branch from base ---
        r = subprocess.run(
            ["git", "checkout", "-b", branch_name, f"origin/{base_branch}"],
            cwd=git_root, capture_output=True, text=True,
        )
        if r.returncode != 0:
            return {"status": "error", "error": f"Branch creation failed: {r.stderr}"}

        # --- Copy evolved skill and commit ---
        abs_skill_path = os.path.join(git_root, repo_skill_path)
        os.makedirs(os.path.dirname(abs_skill_path), exist_ok=True)
        with open(abs_skill_path, "w") as f:
            f.write(evolved_content)

        # Regression cases extracted this run ride the same PR: copy the
        # updated eval files so resolved failures become permanent gate
        # cases the moment the skill merges.
        regression_note = ""
        add_paths = [repo_skill_path]
        marker_path = os.path.join(run_dir, "regression_cases.json")
        if os.path.isfile(marker_path):
            with open(marker_path) as f:
                marker = json.load(f)
            if marker.get("added_eval_cases") or marker.get("added_golden"):
                for rel in ("eval/data/eval_cases.json",
                            "eval/data/golden_evals.json"):
                    src = os.path.join(_repo_root, rel)
                    dst = os.path.join(git_root, rel)
                    if os.path.isfile(src):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        _safe_copy2(src, dst)
                        add_paths.append(rel)
                regression_note = (
                    f"\nRegression gate: +{marker.get('added_eval_cases', 0)} "
                    f"eval case(s) extracted from resolved failures"
                )

        commit_msg = (
            f"Evolve {agent} skill to {version}\n\n"
            f"Meaningful rate: {metrics['baseline_meaningful']}% "
            f"-> {metrics['evolved_meaningful']}%"
            f"{regression_note}\n"
            f"Run: {os.path.basename(run_dir)}"
        )

        subprocess.run(
            ["git", "add"] + add_paths,
            cwd=git_root, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=git_root, capture_output=True,
        )

        # --- Get diff for agy description generation ---
        diff_result = subprocess.run(
            ["git", "diff", f"origin/{base_branch}...HEAD", "--", repo_skill_path],
            cwd=git_root, capture_output=True, text=True,
        )
        diff_text = diff_result.stdout

        # --- Push ---
        r = subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=git_root, capture_output=True, text=True,
        )
        if r.returncode != 0:
            return {"status": "error", "error": f"Push failed: {r.stderr}"}

        # --- Generate PR body (agy if available, fallback otherwise) ---
        body = _generate_pr_body_with_agy(
            agent, version, metrics, evolved_size, run_dir, diff_text,
        )
        if not body:
            body = _default_pr_body(
                agent, version, metrics, evolved_size, run_dir, session_ids,
            )

        # --- Link to issue if provided ---
        if issue_number:
            body += f"\n\nFixes #{issue_number}"

        # --- Create PR via gh CLI ---
        r = subprocess.run(
            [
                "gh", "pr", "create",
                "--base", base_branch,
                "--head", branch_name,
                "--title", title,
                "--body", body,
            ],
            cwd=git_root, capture_output=True, text=True,
        )
        if r.returncode != 0:
            return {"status": "error", "error": f"gh pr create failed: {r.stderr}"}

        pr_url = r.stdout.strip()
        pr_number = pr_url.rstrip("/").split("/")[-1]
        logger.info("Created PR #%s: %s", pr_number, pr_url)

        # Save PR as .md in run directory
        md_path = os.path.join(
            run_dir, f"pr_{pr_number}_evolution.md",
        )
        with open(md_path, "w") as f:
            f.write(f"# {title}\n\n")
            f.write(f"**PR:** {pr_url}\n")
            f.write(f"**Branch:** `{branch_name}`\n\n")
            f.write(body + "\n")
        logger.info("Saved PR .md to %s", md_path)

        return {
            "status": "success",
            "pr_url": pr_url,
            "branch": branch_name,
            "meaningful_rate": metrics["evolved_meaningful"],
            "md_path": md_path,
        }

    except Exception as e:
        logger.error("Failed to create PR: %s", e)
        return {"status": "error", "error": str(e)}

    finally:
        # --- Restore original branch and stash ---
        subprocess.run(
            ["git", "checkout", original_branch],
            cwd=git_root, capture_output=True,
        )
        if stashed:
            subprocess.run(
                ["git", "stash", "pop"],
                cwd=git_root, capture_output=True,
            )


# ---------------------------------------------------------------------------
# Tool: snapshot_skills
# ---------------------------------------------------------------------------


def snapshot_skills(label: str, run_dir: str) -> dict:
    """Save current agent skills to a run directory for later comparison.

    Copies the current SKILL.md files for all registered agents
    into the run directory with the given version label.

    Args:
        label: Version label (e.g. 'v0', 'v1', 'v2').
        run_dir: Path to the run directory.

    Returns:
        Dict with status and paths of saved snapshots.
    """
    os.makedirs(run_dir, exist_ok=True)
    saved = {}
    for name, config in _AGENTS.items():
        src = os.path.join(config["skill_dir"], "SKILL.md")
        if os.path.isfile(src):
            dst = os.path.join(run_dir, f"{label}_{name}_skill.md")
            import shutil
            shutil.copy2(src, dst)
            saved[name] = dst

    return {"status": "success", "label": label, "saved": saved}


# ---------------------------------------------------------------------------
# Tool: restore_skills
# ---------------------------------------------------------------------------


def restore_skills(label: str, run_dir: str) -> dict:
    """Restore agent skills from a previous snapshot in the run directory.

    Copies saved SKILL.md files from the run directory back to the
    agent skill directories.

    Args:
        label: Version label to restore (e.g. 'v0', 'v1').
        run_dir: Path to the run directory containing snapshots.

    Returns:
        Dict with status and paths of restored skills.
    """
    restored = {}
    for name, config in _AGENTS.items():
        src = os.path.join(run_dir, f"{label}_{name}_skill.md")
        dst = os.path.join(config["skill_dir"], "SKILL.md")
        if os.path.isfile(src):
            _safe_copy2(src, dst)
            restored[name] = dst

    if not restored:
        return {"status": "error", "error": f"No snapshots found for label '{label}' in {run_dir}"}

    return {"status": "success", "label": label, "restored": restored}



# ---------------------------------------------------------------------------
# Tool: count_failures
# ---------------------------------------------------------------------------


def count_failures(quality_report_path: str) -> dict:
    """Count failures in a quality report for the evolution gate.

    Returns the number of non-meaningful sessions (total - meaningful).
    Use this to decide whether there is enough failure signal to
    justify running evolution. Default threshold: 30 failures.

    Args:
        quality_report_path: Path to quality report JSON file.

    Returns:
        Dict with total sessions, meaningful count, failure count,
        and whether the threshold is met.
    """
    if not os.path.isfile(quality_report_path):
        return {"error": f"Quality report not found: {quality_report_path}"}

    with open(quality_report_path) as f:
        report = json.load(f)

    summary = report.get("summary", {})
    total = summary.get("total_sessions", 0)
    meaningful = summary.get("meaningful", 0)
    failures = total - meaningful
    min_failures = int(os.getenv("MIN_FAILURES", "30"))

    return {
        "total_sessions": total,
        "meaningful": meaningful,
        "failures": failures,
        "min_failures_threshold": min_failures,
        "should_evolve": failures >= min_failures,
        "meaningful_rate": summary.get("meaningful_rate"),
    }


# ---------------------------------------------------------------------------
# Tool: score_candidate
# ---------------------------------------------------------------------------

def score_candidate(
    candidate_path: str,
    skill_dir: str,
    run_dir: str,
    questions_file: str | None = None,
    concurrency: int = 10,
    max_turns: int = 4,
) -> dict:
    """Score a single evolution candidate by running traffic and scoring.

    Deploys a candidate skill, runs full traffic against it, scores
    the results, and returns the meaningful_rate. Used for best-of-N
    candidate selection.

    Candidate validation is ALWAYS local (in-process agents), even when the
    surrounding loop reads production traffic from BigQuery: the deployed
    stack still serves the old skill revision, so only a local run can
    exercise a not-yet-published candidate.

    IMPORTANT: This modifies the SKILL.md in skill_dir. The caller
    must save/restore skills around calls to this function.

    Args:
        candidate_path: Path to the candidate SKILL.md file.
        skill_dir: Agent skill directory (agent name shortcuts from
            agent_registry.json accepted).
        run_dir: Run directory for output files.
        questions_file: Questions file for scoring (default: full
            demo_conversations.json set).
        concurrency: Concurrent conversations (default: 10).
        max_turns: Max turns per conversation (default: 4).

    Returns:
        Dict with meaningful_rate, output paths, and timing.
    """
    skill_dir = _resolve_skill_dir(skill_dir)

    if not os.path.isfile(candidate_path):
        return {"error": f"Candidate not found: {candidate_path}"}

    skill_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isdir(skill_dir):
        return {"error": f"Skill directory not found: {skill_dir}"}

    if questions_file is None or not os.path.isfile(questions_file):
        questions_file = _questions_file()

    os.makedirs(run_dir, exist_ok=True)
    cand_name = os.path.splitext(os.path.basename(candidate_path))[0]
    results_path = os.path.join(run_dir, f"{cand_name}_traffic.json")
    report_path = os.path.join(run_dir, f"{cand_name}_report.json")

    # Deploy candidate (no-op if the candidate is already the live SKILL.md)
    _safe_copy2(candidate_path, skill_path)

    t0 = time.time()

    # Run quick traffic
    traffic_result = _run_traffic(
        output_path=results_path,
        questions_file=questions_file,
        concurrency=concurrency,
        max_turns=max_turns,
        local=True,
    )
    if traffic_result.get("status") == "error":
        return {"status": "error", "phase": "traffic", "detail": traffic_result}

    # Score with SDK scorer
    sdk_scorer = os.path.join(
        _repo_root, "eval", "scoring", "score_conversations.py",
    )
    cmd = [
        sys.executable, sdk_scorer,
        "-i", results_path,
        "-o", report_path,
        "--concurrency", str(concurrency),
    ]
    # Same eval spec as V0 so candidate and baseline are scored identically
    # (scope-aware: out-of-scope -> declined, not unhelpful).
    _eval_spec = os.path.join(_repo_root, "eval", "data", "eval_spec.json")
    if os.path.isfile(_eval_spec):
        cmd.extend(["--eval-spec", _eval_spec])

    try:
        r = subprocess.run(
            cmd, cwd=_repo_root, capture_output=True, text=True,
            timeout=1800,
        )
        if r.returncode != 0:
            return {
                "status": "error",
                "phase": "scoring",
                "stderr_tail": "\n".join(r.stderr.strip().split("\n")[-10:]),
            }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Candidate scoring timed out"}

    elapsed = time.time() - t0

    if not os.path.isfile(report_path):
        return {"status": "error", "error": "Scorer did not produce output"}

    with open(report_path) as f:
        report = json.load(f)

    summary = report.get("summary", {})
    result = {
        "status": "success",
        "candidate": cand_name,
        "meaningful_rate": summary.get("meaningful_rate"),
        "unhelpful_rate": summary.get("unhelpful_rate"),
        "total_sessions": summary.get("total_sessions"),
        "results_path": results_path,
        "report_path": report_path,
        "elapsed_seconds": round(elapsed, 1),
    }

    # CI-gate pre-check — SUPERVISOR candidates only. Routing and fan-out
    # are supervisor behaviors: with the candidate still deployed on disk,
    # run the same asserts the Eval Gate will run on the PR, so a candidate
    # that scores well on the evolve set by absorbing facts instead of
    # routing loses HERE, before a PR opens (meaningful_rate zeroed for
    # selection). Policy/benefits candidates skip this: they cannot affect
    # routing, and the V0 supervisor's flaky direct-answering would only
    # add noise (verified live: V0 routing flakes 0-3 tests per run).
    if "knowledge_supervisor" not in skill_dir:
        return result
    gate_passed, gate_summary = _golden_gate_check()
    result["gate_passed"] = gate_passed
    result["gate_summary"] = gate_summary
    if gate_passed is False:
        result["raw_meaningful_rate"] = result["meaningful_rate"]
        result["meaningful_rate"] = 0.0
        logger.warning(
            "Candidate %s REFUSED by golden gate pre-check (%s); "
            "meaningful_rate zeroed for selection (raw: %s)",
            cand_name, gate_summary, result["raw_meaningful_rate"],
        )
    return result


def _golden_gate_check(timeout: int = 1200) -> tuple[bool | None, str]:
    """Run the CI gate's routing + compound asserts against the skills
    currently on disk (same tests eval.yml runs on the PR).

    Returns (passed, summary). passed is None when the check could not
    run (pytest missing, unexpected crash) — treated as inconclusive so
    scoring still works in degraded environments.
    """
    cmd = [
        sys.executable, "-m", "pytest",
        os.path.join("eval", "tests", "test_eval.py"),
        "-k", "routing or compound",
        "-q", "--tb=no", "-p", "no:cacheprovider",
    ]
    try:
        r = subprocess.run(
            cmd, cwd=_repo_root, capture_output=True, text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return None, "pytest unavailable — gate pre-check skipped"
    except subprocess.TimeoutExpired:
        return None, "gate pre-check timed out — treated as inconclusive"
    tail = (r.stdout or "").strip().split("\n")[-1] if r.stdout else ""
    if r.returncode == 0:
        return True, tail or "all gate asserts passed"
    if "No module named pytest" in (r.stderr or ""):
        return None, "pytest unavailable — gate pre-check skipped"
    return False, tail or f"pytest exit {r.returncode}"


# ---------------------------------------------------------------------------
# Tool: read_skill
# ---------------------------------------------------------------------------


def read_skill(agent_name: str) -> dict:
    """Read the current SKILL.md content for an agent.

    Use this to review an evolved skill before running traffic.
    Check for: appropriate size (8-15KB), keyword mappings table,
    anti-patterns section, no excessive repetition.

    Args:
        agent_name: Agent name from agent_registry.json.

    Returns:
        Dict with skill content, size, and version metadata.
    """
    if agent_name not in _AGENTS:
        available = ", ".join(sorted(_AGENTS.keys()))
        return {"error": f"Unknown agent: {agent_name}. Available: {available}"}
    skill_dir = _AGENTS[agent_name]["skill_dir"]

    skill_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_path):
        return {"error": f"SKILL.md not found at {skill_path}"}

    with open(skill_path) as f:
        content = f.read()

    # Extract version from YAML frontmatter, prefix with 'v' if needed
    version = "unknown"
    if content.startswith("---"):
        import re
        m = re.search(r'version:\s*["\']?(\S+)', content)
        if m:
            version = m.group(1).strip('"\'')
            if not version.startswith("v"):
                version = f"v{version}"

    # Count sections
    sections = [line for line in content.split("\n") if line.startswith("## ")]

    return {
        "agent": agent_name,
        "version": version,
        "size_chars": len(content),
        "size_kb": round(len(content) / 1024, 1),
        "sections": [s.strip("# ").strip() for s in sections],
        "content": content,
    }


# ---------------------------------------------------------------------------
# Tool: list_agents
# ---------------------------------------------------------------------------


def list_agents() -> dict:
    """List all registered agents available for evolution.

    Returns agent names, skill directories, and labels from the
    agent registry. Use this to discover which agents can be evolved.

    Returns:
        Dict mapping agent name to skill_dir and label.
    """
    return {
        name: {"skill_dir": config["skill_dir"], "label": config.get("label", name)}
        for name, config in _AGENTS.items()
    }


# ---------------------------------------------------------------------------
# Tool: compare_versions
# ---------------------------------------------------------------------------


def compare_versions(run_dir: str) -> dict:
    """Generate a comparison table of all scored versions in a run.

    Scans the run directory for quality reports (*_quality_report.json,
    v1_quality_report.json, etc.) and produces a summary table.

    Args:
        run_dir: Path to the run directory.

    Returns:
        Dict with comparison table and per-version metrics.
    """
    if not os.path.isdir(run_dir):
        return {"error": f"Run directory not found: {run_dir}"}

    import glob as glob_mod

    reports = sorted(glob_mod.glob(os.path.join(run_dir, "*_quality_report.json")))
    if not reports:
        return {"error": "No quality reports found in run directory"}

    versions = []
    for report_path in reports:
        fname = os.path.basename(report_path)
        label = fname.split("_quality_report")[0]
        with open(report_path) as f:
            report = json.load(f)
        summary = report.get("summary", {})
        versions.append({
            "version": label,
            "total_sessions": summary.get("total_sessions", 0),
            "meaningful": summary.get("meaningful", 0),
            "meaningful_rate": summary.get("meaningful_rate", 0),
            "unhelpful": summary.get("unhelpful", 0),
            "unhelpful_rate": summary.get("unhelpful_rate", 0),
        })

    # Authoritative evolved-skill score recorded by the incumbent-guarded
    # selection (scored on the SAME eval set as v0). Prefer this over noisy
    # re-scored *_quality_report.json files, which compare_versions cannot even
    # see for the deployed skill (it is saved as *_report.json, not
    # *_quality_report.json).
    evolved_score_path = os.path.join(run_dir, "evolved_score.json")
    if os.path.isfile(evolved_score_path):
        try:
            with open(evolved_score_path) as f:
                es = json.load(f)
            if not any(v["version"] == "evolved" for v in versions):
                versions.append({
                    "version": "evolved",
                    "total_sessions": versions[0]["total_sessions"]
                    if versions else 0,
                    "meaningful": 0,
                    "meaningful_rate": es.get("meaningful_rate", 0),
                    "unhelpful": 0,
                    "unhelpful_rate": 0,
                })
        except Exception:  # noqa: BLE001
            pass

    # Compute deltas
    for i, v in enumerate(versions):
        if i == 0:
            v["delta"] = None
        else:
            prev_rate = versions[i - 1]["meaningful_rate"] or 0
            curr_rate = v["meaningful_rate"] or 0
            v["delta"] = round(curr_rate - prev_rate, 1)

    # Find peak version (excluding v0 baseline)
    evolved = [v for v in versions if v["version"] != "v0"]
    best = max(evolved, key=lambda v: v["meaningful_rate"]) if evolved else versions[0]

    # Build text table
    header = "| Version | Sessions | Meaningful Rate | Delta | Best |"
    sep = "|---------|----------|-----------------|-------|------|"
    rows = [header, sep]
    for v in versions:
        delta = f"+{v['delta']}pp" if v["delta"] and v["delta"] > 0 else (
            f"{v['delta']}pp" if v["delta"] else "-"
        )
        marker = " <-- " if v["version"] == best["version"] else ""
        rows.append(
            f"| {v['version']:<7} | {v['total_sessions']:>8} | "
            f"{v['meaningful_rate']:>13}% | {delta:>5} | {marker:>4} |"
        )

    return {
        "status": "success",
        "versions": versions,
        "best_version": best["version"],
        "best_meaningful_rate": best["meaningful_rate"],
        "table": "\n".join(rows),
    }


