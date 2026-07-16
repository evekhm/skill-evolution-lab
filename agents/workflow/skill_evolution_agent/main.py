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

"""Runner for the Skill Evolution Agent.

Can run as a CLI, Cloud Run Job, or test individual tools.

Usage:
    # Full loop: traffic -> score -> evolve -> PR
    python main.py --full-loop

    # From existing quality report:
    python main.py --report path/to/quality_report.json
    python main.py --report path/to/quality_report.json --mode coevolve

    # Test tools only:
    python main.py --test
"""

import argparse
import asyncio
import logging
import os
import sys
import uuid

# Ensure this package is importable when run directly
_agent_dir = os.path.dirname(os.path.abspath(__file__))
_workflow_dir = os.path.dirname(_agent_dir)
_agents_dir = os.path.dirname(_workflow_dir)
_project_root = os.path.dirname(_agents_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from google.genai import types  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Suppress noisy libraries
for _noisy in (
    "google.genai", "google_genai", "google.adk", "google_adk",
    "google.auth", "google_auth", "httpx", "httpcore",
):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

logger = logging.getLogger("skill_evolution.run")

_QUESTIONS_FULL = os.path.join(
    _project_root, "eval", "data", "questions", "demo_conversations.json",
)
_QUESTIONS_QUICK = os.path.join(
    _project_root, "eval", "data", "questions", "demo_quick.json",
)


def _run_traffic_orchestration(
    output_path: str,
    questions_file: str,
    concurrency: int = 10,
    max_turns: int = 4,
    local: bool | None = None,
) -> dict:
    """Pre-flight: generate traffic before starting the agent.

    ``local`` defaults from the TRAFFIC_MODE env var: 'local' (default) runs
    in-process agents; 'deployed' drives the deployed Agent Engine supervisor,
    whose agents log the sessions to BigQuery themselves.
    """
    import shutil
    import subprocess
    import time

    if local is None:
        local = os.environ.get("TRAFFIC_MODE", "local").lower() != "deployed"

    if not os.path.isfile(questions_file):
        return {"error": f"Questions file not found: {questions_file}"}

    # Honor EVAL_MAX_TURNS so the pre-flight V0 traffic matches the rest of the
    # loop. Multi-turn lets a follow-up recover a half-answered compound question,
    # which hides the failures the analysts need to see; max_turns=1 surfaces them.
    env_turns = os.environ.get("EVAL_MAX_TURNS")
    if env_turns:
        max_turns = int(env_turns)

    out_dir = os.path.dirname(output_path)
    os.makedirs(out_dir, exist_ok=True)

    cmd = [
        sys.executable,
        os.path.join(_project_root, "agents", "workflow", "traffic_generator", "main.py"),
        "--multi-turn",
        "--from-file", questions_file,
        "-o", output_path,
        "--concurrency", str(concurrency),
        "--max-turns", str(max_turns),
    ]
    if local:
        cmd.extend(["--local", "--local-agents"])

    logger.info("Pre-flight traffic: %s", " ".join(cmd))
    # Local pre-flight traffic stays out of the production analytics table
    # (it would dilute the next BigQuery-sourced report); deployed traffic is
    # logged by the deployed agents themselves and is the real thing.
    traffic_env = {
        k: v for k, v in os.environ.items()
        if not local or k not in ("DATASET_ID", "TABLE_ID", "DATASET_LOCATION")
    }
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, cwd=_project_root, capture_output=True, text=True,
            timeout=7200,
            env=traffic_env,
        )
        elapsed = time.time() - t0
        if result.returncode != 0:
            stderr_tail = "\n".join(result.stderr.strip().split("\n")[-20:])
            logger.error("Traffic generation failed:\n%s", stderr_tail)
            return {"status": "error", "returncode": result.returncode,
                    "stderr_tail": stderr_tail, "elapsed_seconds": round(elapsed, 1)}
        logger.info("Pre-flight traffic done in %.1fs", elapsed)
        return {"status": "success", "output_path": output_path,
                "elapsed_seconds": round(elapsed, 1)}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Traffic generation timed out (2h)"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _bigquery_quality_report(run_dir: str) -> str | None:
    """Pre-flight from real traces: score BigQuery sessions instead of
    generating synthetic traffic (QUALITY_SOURCE=bigquery).

    Returns the saved report path, or None when fewer than MIN_SESSIONS
    sessions exist — the caller then falls back to generated traffic.
    """
    min_sessions = int(os.environ.get("MIN_SESSIONS", "20"))
    time_period = os.environ.get("EVAL_TIME_PERIOD", "7d")
    agent_version = os.environ.get("AGENT_VERSION") or None
    try:
        from agents.workflow.quality_agent.tools import (
            run_quality_report as _bq_quality_report,
        )

        result = _bq_quality_report(
            time_period=time_period,
            output_dir=run_dir,
            agent_version=agent_version,
        )
        total = result.get("summary", {}).get("total_sessions", 0)
        if total < min_sessions:
            logger.warning(
                "BigQuery has %d sessions (< MIN_SESSIONS=%d) for period=%s "
                "version=%s — falling back to generated traffic.",
                total, min_sessions, time_period, agent_version or "any",
            )
            return None
        saved = result.get("report_path") or os.path.join(
            run_dir, "quality_report.json"
        )
        report_path = os.path.join(run_dir, "v0_quality_report.json")
        if os.path.abspath(saved) != os.path.abspath(report_path):
            os.replace(saved, report_path)
        logger.info(
            "Pre-flight quality report from BigQuery: %d sessions -> %s",
            total, report_path,
        )
        return report_path
    except Exception as e:
        logger.warning(
            "BigQuery quality report failed (%s) — falling back to "
            "generated traffic.", e,
        )
        return None


def _run_scoring_orchestration(
    traffic_path: str,
    output_path: str,
    concurrency: int = 10,
) -> dict:
    """Pre-flight: score traffic before starting the agent."""
    import subprocess
    import time

    if not os.path.isfile(traffic_path):
        return {"error": f"Traffic file not found: {traffic_path}"}

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    cmd = [
        sys.executable,
        os.path.join(_project_root, "eval", "scoring", "score_conversations.py"),
        "-i", traffic_path,
        "-o", output_path,
        "--concurrency", str(concurrency),
        "--tag-turns",
        "--trajectory-samples", "all",
        "--report",
    ]
    # Ground scoring with the eval spec (scope + golden Q&A + tools). Without
    # it the judge has no scope, so out-of-scope questions are scored
    # 'unhelpful' instead of 'declined' and the meaningful rate is capped.
    _eval_spec = os.path.join(_project_root, "eval", "data", "eval_spec.json")
    if os.path.isfile(_eval_spec):
        cmd.extend(["--eval-spec", _eval_spec])

    logger.info("Pre-flight scoring: %s", " ".join(cmd))
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, cwd=_project_root, capture_output=True, text=True,
            timeout=1800,
        )
        elapsed = time.time() - t0
        if result.returncode != 0:
            stderr_tail = "\n".join(result.stderr.strip().split("\n")[-10:])
            logger.error("Quality scoring failed:\n%s", stderr_tail)
            return {"status": "error", "returncode": result.returncode,
                    "stderr_tail": stderr_tail, "elapsed_seconds": round(elapsed, 1)}
        logger.info("Pre-flight scoring done in %.1fs", elapsed)
        return {"status": "success", "output_path": output_path,
                "elapsed_seconds": round(elapsed, 1)}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Quality scoring timed out (30min)"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def run_test():
    """Test individual tools without running the agent."""
    from agents.workflow.skill_evolution_agent.tools import (
        read_current_eval_cases,
    )

    print("--- Testing read_current_eval_cases ---")
    cases = read_current_eval_cases()
    if "error" in cases:
        print(f"  Error: {cases['error']}")
    else:
        n = len(cases.get("eval_cases", []))
        print(f"  Total eval cases: {n}")
        if cases.get("eval_cases"):
            print(f"  Sample: {cases['eval_cases'][0]}")

    print("\n--- Tools loaded successfully ---")
    print("Available tools:")
    print("  - run_evolution")
    print("  - detect_bottleneck_tool")
    print("  - run_coevolution")
    print("  - extract_eval_cases")
    print("  - read_current_eval_cases")
    print("\nRun with --report to start the agent.")


async def run_evolution_agent(
    report_path: str | None = None,
    mode: str = "auto",
    run_dir: str | None = None,
    rounds: int | None = None,
    candidates: int | None = None,
    min_failures: int | None = None,
    quick: bool = False,
    from_issue: int | None = None,
) -> str:
    """Run the Skill Evolution Agent and return its response."""
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import (
        InMemorySessionService,
    )

    from agents.workflow.skill_evolution_agent.agent import app

    session_service = InMemorySessionService()
    runner = Runner(
        app=app,
        session_service=session_service,
        auto_create_session=True,
    )

    user_id = f"skill_evolution_{uuid.uuid4().hex[:8]}"
    session_id = f"evolution_{uuid.uuid4().hex[:8]}"

    # Set env vars for tools to pick up (only when overridden)
    if min_failures is not None:
        os.environ["MIN_FAILURES"] = str(min_failures)

    # Build override notes — only mention params that were explicitly set
    overrides = []
    if rounds is not None:
        overrides.append(f"Maximum rounds: {rounds}")
    if candidates is not None:
        overrides.append(f"Candidates: {candidates} (best-of-N selection)")
    if min_failures is not None:
        overrides.append(f"Min failures threshold: {min_failures}")
    overrides_note = "\n".join(overrides) + "\n" if overrides else ""

    if from_issue is not None:
        # Issue-triggered mode: parse quality issue and run evolution
        if run_dir is None:
            import time as _time
            ts = _time.strftime("%Y-%m-%d_%H%M%S")
            run_dir = os.path.join(
                _project_root, "eval", "runs", f"{ts}_issue_{from_issue}",
            )

        prompt = (
            f"A quality issue has been filed: #{from_issue}.\n"
            f"Run directory: {run_dir}\n"
            f"{overrides_note}"
            "\nFollow the issue-triggered evolution workflow:\n\n"
            f"1. parse_quality_issue({from_issue}) — read the issue details\n"
            "2. Identify the agent to evolve from the issue metadata\n"
            "3. Extract the 'Quality report' URI from the issue metadata table.\n"
            "   - If it starts with gs://, call download_from_gcs to get it locally\n"
            "   - If it's a local path, use it directly\n"
            "4. snapshot_skills('initial', run_dir)\n"
            "5. count_failures on the quality report\n"
            "6. If enough failures: detect_bottleneck_tool, run_evolution\n"
            "7. Score candidates if using best-of-N\n"
            "8. snapshot_skills for evolved version\n"
            "9. Run validation traffic on evolved skill, score, report delta\n"
            "10. compare_versions(run_dir)\n"
            "11. upload_run_to_gcs if configured\n"
            "12. push_skill_to_registry(run_dir, version, agent) — new Skill\n"
            "    Registry revision (only when the evolved skill beat the baseline)\n"
            f"13. create_evolution_pr(issue_number={from_issue}) — "
            f"PR with Fixes #{from_issue}; mention the registry revision in the body\n\n"
            "IMPORTANT: Use the quality report from the issue — do NOT generate\n"
            "synthetic traffic. The quality report contains real production data.\n\n"
            "Do NOT restore skills — the evolved skill stays deployed.\n"
            "Report the results."
        )
        logger.info(
            "Starting issue-triggered evolution: issue=#%s, run_dir=%s",
            from_issue, run_dir,
        )

    elif report_path is None:
        # Full loop mode: orchestrate traffic + scoring BEFORE starting agent
        if run_dir is None:
            import time as _time
            ts = _time.strftime("%Y-%m-%d_%H%M%S")
            run_dir = os.path.join(_project_root, "eval", "runs", f"{ts}_evolution")

        os.makedirs(run_dir, exist_ok=True)
        # Honor EVAL_QUESTIONS_FILE so the held-out split (Trace2Skill §2.1)
        # works: pre-flight V0 traffic + failure mining must use D_evolve, not
        # the full set, or patches would derive from held-out test questions.
        questions_file = os.environ.get("EVAL_QUESTIONS_FILE") or (
            _QUESTIONS_QUICK if quick else _QUESTIONS_FULL
        )

        # Pre-flight source: real BigQuery traces (QUALITY_SOURCE=bigquery)
        # with a generated-traffic fallback below MIN_SESSIONS, or generated
        # traffic directly (default).
        report_path = None
        if os.environ.get("QUALITY_SOURCE", "synthetic").lower() == "bigquery":
            report_path = _bigquery_quality_report(run_dir)

        if report_path is None:
            # Pre-flight: generate traffic
            traffic_path = os.path.join(run_dir, "v0_traffic.json")
            traffic_result = _run_traffic_orchestration(
                output_path=traffic_path,
                questions_file=questions_file,
            )
            if traffic_result.get("status") == "error":
                logger.error("Pre-flight traffic failed: %s", traffic_result)
                return f"ERROR: Traffic generation failed: {traffic_result}"

            # Pre-flight: score quality
            report_path = os.path.join(run_dir, "v0_quality_report.json")
            scoring_result = _run_scoring_orchestration(
                traffic_path=traffic_path,
                output_path=report_path,
            )
            if scoring_result.get("status") == "error":
                logger.error("Pre-flight scoring failed: %s", scoring_result)
                return f"ERROR: Quality scoring failed: {scoring_result}"

        logger.info("Pre-flight complete. Starting agent with report: %s", report_path)

        questions_note = "Use 22-question quick set for candidate scoring." if not quick else "Use 22-question quick set for ALL traffic."
        prompt = (
            f"Quality report is ready at {report_path}.\n"
            f"Run directory: {run_dir}\n"
            f"{overrides_note}"
            f"{questions_note}\n\n"
            "Initial traffic and quality report have been generated.\n"
            "Follow the evolution algorithm from your skill. Decide rounds,\n"
            "candidates, and failure thresholds based on the quality data —\n"
            "unless overrides are listed above.\n\n"
            "1. snapshot_skills('initial', run_dir) — save current skills\n"
            "2. For each round:\n"
            "   a. count_failures on the quality report\n"
            "   b. If enough failures: detect_bottleneck_tool, then evolve\n"
            "   c. Score candidates, pick best\n"
            "   d. snapshot_skills for evolved version\n"
            "   e. Run validation traffic on evolved skill (via score_candidate)\n"
            "   f. Report delta from previous version\n"
            "   g. If failures drop below threshold, stop — no more rounds\n"
            "3. compare_versions(run_dir) to show final table\n"
            "4. extract_eval_cases to save regression tests\n"
            "5. Upload to GCS if configured\n"
            "6. If the best evolved version beat the baseline:\n"
            "   push_skill_to_registry(run_dir, version, agent) — new Skill\n"
            "   Registry revision — then create_evolution_pr; mention the\n"
            "   registry revision in the PR body\n"
            "Do NOT restore skills — the evolved skill stays deployed.\n"
            "Report the results."
        )
        logger.info(
            "Starting full evolution loop: rounds=%s, candidates=%s, "
            "min_failures=%s, quick=%s, run_dir=%s",
            rounds or "agent-decided", candidates or "agent-decided",
            min_failures or "agent-decided", quick, run_dir,
        )
    elif mode == "auto":
        if run_dir:
            questions_note = "Use 22-question quick set for candidate scoring." if not quick else "Use 22-question quick set for ALL traffic."
            prompt = (
                f"Quality report is ready at {report_path}.\n"
                f"Run directory: {run_dir}\n"
                f"{overrides_note}"
                f"{questions_note}\n\n"
                "Initial skills and snapshots are already in the run directory.\n"
                "Follow the evolution algorithm from your skill. Decide rounds,\n"
                "candidates, and failure thresholds based on the quality data —\n"
                "unless overrides are listed above.\n\n"
                "Start from the gate check:\n"
                "1. count_failures on the quality report\n"
                "2. If enough failures: detect_bottleneck_tool, then evolve\n"
                "3. Score candidates, pick best\n"
                "4. snapshot_skills for evolved version\n"
                "5. Run validation traffic on evolved skill, score, report delta\n"
                "6. count_failures on the new report. If below threshold,\n"
                "   STOP — do not snapshot a duplicate version.\n"
                "   Otherwise repeat evolution for the next round.\n"
                "7. compare_versions(run_dir) for final table\n"
                "Do NOT restore skills — the evolved skill stays deployed.\n"
                "Only report versions that were actually evolved."
            )
        else:
            prompt = (
                f"Analyze the quality report at {report_path}. "
                f"{overrides_note}"
                "Detect the bottleneck, evolve the appropriate agent(s), "
                "extract regression test cases, and report your findings."
            )
    elif mode == "coevolve":
        prompt = (
            f"Run co-evolution on the quality report at {report_path}. "
            "Use run_coevolution which handles bottleneck detection and "
            "multi-agent evolution automatically. Then extract regression "
            "test cases."
        )
    else:
        prompt = (
            f"Run skill evolution on the {mode} agent using the quality "
            f"report at {report_path}. Call run_evolution with "
            f'skill_dir="{mode}". Then extract regression test cases.'
        )

    if report_path:
        logger.info("Starting skill evolution agent: %s mode", mode)
        logger.info("Quality report: %s", report_path)

    response_parts = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        ),
    ):
        if event.author != "user" and event.content and not event.partial:
            for part in event.content.parts:
                if part.text:
                    response_parts.append(part.text)

    return "\n".join(response_parts)


def _run_batch_mode(args, common_kwargs) -> str:
    """Batch mode: check accumulated quality issues, run evolution if threshold met."""
    import json as _json
    import re
    import subprocess

    config_path = os.path.join(
        _project_root, "eval", "data", "quality_config.json",
    )
    min_issues = 10
    if os.path.isfile(config_path):
        with open(config_path) as f:
            cfg = _json.load(f)
        min_issues = int(
            os.getenv(
                "EVOLUTION_MIN_OPEN_ISSUES",
                cfg.get("evolution", {}).get("min_open_issues", 10),
            )
        )

    try:
        r = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--label", "quality",
             "--json", "number,title,createdAt,body", "--limit", "200"],
            capture_output=True, text=True, cwd=_project_root,
        )
        if r.returncode != 0:
            logger.error("gh issue list failed: %s", r.stderr)
            sys.exit(1)
        issues = _json.loads(r.stdout)
    except FileNotFoundError:
        logger.error("gh CLI not available — required for --batch mode")
        sys.exit(1)

    logger.info("Open quality issues: %d (threshold: %d)", len(issues), min_issues)
    if len(issues) < min_issues:
        msg = (
            f"Not enough accumulated issues: {len(issues)}/{min_issues}. "
            "Skipping evolution."
        )
        logger.info(msg)
        print(msg)
        return msg

    # TODO: Currently only uses the most recent quality report. When issues
    # span multiple quality runs, we should download and merge all distinct
    # reports to give the evolution agent the full picture. Each issue links
    # to its report via the metadata table — collect all unique URIs, download
    # each, and merge their session lists before passing to the agent.
    report_uri = None
    for issue in sorted(issues, key=lambda i: i["createdAt"], reverse=True):
        body = issue.get("body", "")
        match = re.search(r"\|\s*Quality report\s*\|\s*`([^`]+)`\s*\|", body)
        if match:
            report_uri = match.group(1)
            break

    if not report_uri:
        logger.warning("No quality report URI found in any open issue")
        report_path = None
    elif report_uri.startswith("gs://"):
        run_dir = args.run_dir or os.path.join(
            _project_root, "eval", "runs",
            f"{__import__('time').strftime('%Y-%m-%d_%H%M%S')}_batch",
        )
        os.makedirs(run_dir, exist_ok=True)
        local_report = os.path.join(run_dir, "quality_report.json")
        from agents.workflow.gcs_utils import download_from_gcs
        dl = download_from_gcs(report_uri, local_report)
        if dl.get("status") != "success":
            logger.error("GCS download failed: %s", dl)
            sys.exit(1)
        report_path = local_report
    else:
        report_path = report_uri if os.path.isfile(report_uri) else None

    issue_numbers = [i["number"] for i in issues]
    logger.info(
        "Running batch evolution for %d issues: %s",
        len(issue_numbers), issue_numbers[:10],
    )

    return asyncio.run(
        run_evolution_agent(
            report_path=report_path,
            mode=args.mode if hasattr(args, "mode") else "auto",
            run_dir=args.run_dir,
            **common_kwargs,
        )
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run Skill Evolution Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --full-loop                              # agent decides everything
  %(prog)s --full-loop --rounds 1 --quick           # override: single round, quick
  %(prog)s --full-loop --candidates 5               # override: best-of-5
  %(prog)s --report eval/runs/.../quality_report.json  # from report
  %(prog)s --report report.json --mode coevolve
  %(prog)s --report report.json --mode policy_agent
  %(prog)s --test
        """,
    )
    # Set AGENT_REGISTRY env var early so tools.py picks it up at import
    for i, arg in enumerate(sys.argv):
        if arg == "--agent-registry" and i + 1 < len(sys.argv):
            os.environ["AGENT_REGISTRY"] = sys.argv[i + 1]
            break

    from agents.workflow.skill_evolution_agent.tools import _AGENTS
    agent_names = list(_AGENTS.keys())

    parser.add_argument(
        "--agent-registry",
        metavar="PATH",
        help="Path to agent_registry.json. Overrides AGENT_REGISTRY env var. "
        "Defaults to eval/skill_evolution/agent_registry.json.",
    )
    parser.add_argument(
        "--from-issue",
        type=int,
        metavar="N",
        help="GitHub issue number to process (parse issue, evolve, create PR with Fixes #N)",
    )
    parser.add_argument(
        "--report",
        help="Path to quality report JSON file",
    )
    parser.add_argument(
        "--full-loop",
        action="store_true",
        help="Run the full pipeline: traffic -> score -> evolve -> PR",
    )
    parser.add_argument(
        "--run-dir",
        help="Directory for run artifacts (default: timestamped under eval/runs/)",
    )
    parser.add_argument(
        "--mode",
        default="auto",
        choices=["auto", "coevolve"] + agent_names,
        help=(
            "Evolution mode: auto (detect bottleneck), coevolve "
            "(multi-agent), or a specific agent name (default: auto). "
            f"Available agents: {', '.join(agent_names)}"
        ),
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=None,
        help="Maximum evolution rounds (default: agent decides based on evolution gate)",
    )
    parser.add_argument(
        "--candidates",
        type=int,
        default=None,
        help="Number of consolidation candidates for best-of-N (default: agent decides)",
    )
    parser.add_argument(
        "--min-failures",
        type=int,
        default=None,
        help="Minimum failures required to trigger evolution (default: agent decides)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use 22-question quick set for all traffic (faster, less signal)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Batch mode: check if enough quality issues have accumulated, "
        "then run evolution using the most recent quality report",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test tools only, don't run the agent",
    )
    args = parser.parse_args()

    if args.test:
        run_test()
        return

    common_kwargs = dict(
        rounds=args.rounds,
        candidates=args.candidates,
        min_failures=args.min_failures,
        quick=args.quick,
    )

    if args.batch:
        result = _run_batch_mode(args, common_kwargs)
    elif args.from_issue:
        result = asyncio.run(
            run_evolution_agent(
                from_issue=args.from_issue,
                run_dir=args.run_dir, **common_kwargs
            )
        )
    elif args.full_loop:
        result = asyncio.run(
            run_evolution_agent(
                report_path=None, run_dir=args.run_dir, **common_kwargs
            )
        )
    elif args.report:
        report_path = args.report
        if report_path.startswith("gs://"):
            local_dir = args.run_dir or os.path.join(
                _project_root, "eval", "runs",
                f"{__import__('time').strftime('%Y-%m-%d_%H%M%S')}_evolution",
            )
            os.makedirs(local_dir, exist_ok=True)
            local_report = os.path.join(local_dir, "quality_report.json")
            logger.info("Downloading report from GCS: %s", report_path)
            from agents.workflow.gcs_utils import download_from_gcs
            dl = download_from_gcs(report_path, local_report)
            if dl.get("status") != "success":
                logger.error("GCS download failed: %s", dl)
                sys.exit(1)
            report_path = local_report
        elif not os.path.isfile(report_path):
            logger.error("Quality report not found: %s", report_path)
            sys.exit(1)
        result = asyncio.run(
            run_evolution_agent(
                report_path=report_path, mode=args.mode,
                run_dir=args.run_dir, **common_kwargs
            )
        )
    else:
        # Cloud Run Job / GitHub Actions mode: check env vars
        issue_num = os.getenv("ISSUE_NUMBER")
        report = os.getenv("QUALITY_REPORT_PATH")
        full_loop = os.getenv("FULL_LOOP", "").lower() in ("true", "1", "yes")
        if issue_num:
            result = asyncio.run(
                run_evolution_agent(
                    from_issue=int(issue_num),
                    run_dir=args.run_dir, **common_kwargs
                )
            )
        elif full_loop:
            result = asyncio.run(
                run_evolution_agent(
                    report_path=None, run_dir=args.run_dir, **common_kwargs
                )
            )
        elif report:
            if not os.path.isfile(report):
                logger.error("Quality report not found: %s", report)
                sys.exit(1)
            result = asyncio.run(
                run_evolution_agent(
                    report_path=report, mode=args.mode, **common_kwargs
                )
            )
        else:
            parser.error(
                "--from-issue, --report, or --full-loop is required "
                "(or set ISSUE_NUMBER / QUALITY_REPORT_PATH / FULL_LOOP env vars)"
            )
            return  # unreachable, but makes type checker happy

    print("\n" + "=" * 60)
    print("SKILL EVOLUTION REPORT")
    print("=" * 60)
    print(result)
    print("=" * 60)


if __name__ == "__main__":
    main()
