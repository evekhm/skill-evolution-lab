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

"""Runner for quality_agent.

Can run as a one-shot CLI, Cloud Run Job, or test individual tools.

Usage:
    python main.py                       # default: last 6h
    python main.py --period 1d           # last 24 hours
    python main.py --dry-run             # analyze but write files instead of GitHub issues
    python main.py --dry-run --period 1d # dry-run with custom period
    python main.py --test                # test tools only (no agent)
    python main.py --test 1h             # test with custom time period
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime

# Ensure this package is importable when run directly
_agent_dir = os.path.dirname(os.path.abspath(__file__))
_workflow_dir = os.path.dirname(_agent_dir)
_agents_dir = os.path.dirname(_workflow_dir)
if _agents_dir not in sys.path:
    sys.path.insert(0, _agents_dir)
# Also add project root for local dev
_project_root = os.path.dirname(_agents_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from google.genai import types

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("quality_agent.run")


def run_test(time_period: str = "1h"):
    """Test individual tools without running the agent."""
    from agents.workflow.quality_agent.tools import run_quality_report

    print("--- Testing run_quality_report ---")
    print(f"Running quality report for last {time_period}...")
    result = run_quality_report(time_period)
    print(json.dumps(result.get("summary", {}), indent=2))
    sessions = result.get("sessions", [])
    if sessions:
        print(f"\nSample session:")
        print(json.dumps(sessions[0], indent=2))
    else:
        print("No sessions found.")

    print("\n--- Testing GitHub connection ---")
    import subprocess
    # Try gh CLI first
    try:
        r = subprocess.run(
            ["gh", "repo", "view", "--json", "name,owner"],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            info = json.loads(r.stdout)
            print(f"[gh CLI] Connected to: {info['owner']['login']}/{info['name']}")
            r2 = subprocess.run(
                ["gh", "issue", "list", "--state", "open", "--label", "quality",
                 "--json", "number", "--limit", "100"],
                capture_output=True, text=True,
            )
            if r2.returncode == 0:
                issues = json.loads(r2.stdout)
                print(f"[gh CLI] Open quality issues: {len(issues)}")
        else:
            print(f"[gh CLI] Not available: {r.stderr.strip()}")
    except FileNotFoundError:
        print("[gh CLI] Not installed")

    # Try PyGithub fallback
    try:
        from agents.workflow.quality_agent.tools import _get_github_repo
        repo = _get_github_repo()
        print(f"[PyGithub] Connected to: {repo.full_name}")
        print(f"[PyGithub] Open issues: {repo.get_issues(state='open').totalCount}")
    except Exception as e:
        print(f"[PyGithub] Not available: {e}")

    print("\nAll tools OK. Run without --test to start the agent.")


async def run_patrol(
    time_period: str,
    run_dir: str | None = None,
    agent_version: str | None = None,
) -> str:
    """Run the Quality Agent and return its response."""
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from agents.workflow.quality_agent.agent import app

    if run_dir is None:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        run_dir = os.path.join(_project_root, "eval", "runs", f"{ts}_quality")
    os.makedirs(run_dir, exist_ok=True)

    session_service = InMemorySessionService()
    runner = Runner(
        app=app,
        session_service=session_service,
        auto_create_session=True,
    )

    user_id = f"quality_agent_{uuid.uuid4().hex[:8]}"
    session_id = f"quality_{uuid.uuid4().hex[:8]}"

    version_instruction = ""
    if agent_version:
        version_instruction = (
            f"Filter to agent_version='{agent_version}' when calling "
            f"run_quality_report. Pass agent_version='{agent_version}' "
            f"to every create_github_issue call. "
        )

    prompt = (
        f"Run a quality report for the last {time_period}. "
        f"{version_instruction}"
        f"Save the report to output_dir='{run_dir}'. "
        "Analyze all failures, create GitHub issues for anything needing "
        "human review. Report your findings."
    )

    logger.info(f"Starting quality agent for period: {time_period}")

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
                if hasattr(part, "function_call") and part.function_call:
                    print(
                        f"  -> calling {part.function_call.name}({dict(part.function_call.args)})"
                    )

    return "\n".join(response_parts)


def main():
    parser = argparse.ArgumentParser(description="Run Quality Agent")
    parser.add_argument(
        "--period",
        default=os.getenv("TIME_PERIOD", "6h"),
        help="Time period to analyze (e.g., '6h', '1d', 'all'). Default: 6h",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write issue/PR markdown files locally instead of creating them on GitHub. "
        "Output goes to agents/workflow/quality_agent/dry_run_output/.",
    )
    parser.add_argument(
        "--agent-version",
        default=os.getenv("AGENT_VERSION"),
        help="Filter BQ sessions to this agent version and tag issues. "
        "Default: AGENT_VERSION env var.",
    )
    parser.add_argument(
        "--test",
        nargs="?",
        const="1h",
        default=None,
        help="Test tools only, no agent. Optional time period (default: 1h).",
    )
    args = parser.parse_args()

    if args.test is not None:
        run_test(args.test)
        return

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = os.path.join(_project_root, "eval", "runs", f"{ts}_quality")

    if args.dry_run:
        from agents.workflow.quality_agent.tools import enable_dry_run

        dry_run_dir = os.path.join(run_dir, "issues")
        enable_dry_run(dry_run_dir)
        logger.info("Dry-run mode: issues will be written to %s", dry_run_dir)

    result = asyncio.run(run_patrol(
        args.period, run_dir=run_dir, agent_version=args.agent_version,
    ))
    print("\n" + "=" * 60)
    print("QUALITY AGENT REPORT")
    print("=" * 60)
    print(result)
    print(f"\nRun directory: {run_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
