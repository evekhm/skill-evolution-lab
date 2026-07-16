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

"""Skill Evolution Agent -- evolves agent skills from execution trajectories.

This agent runs on a schedule (weekly via Cloud Scheduler or manually).
It reads a quality report, detects the bottleneck agent, runs the
evolution pipeline, and extracts failed conversations as regression
test eval cases.

The evolution pipeline:
1. Partitions conversations into successes (T+) and failures (T-)
2. Dispatches ~100 analysts in parallel to examine each trajectory
3. Consolidates all patches into an evolved SKILL.md
4. Optionally generates best-of-N candidates
"""

import os

import google.auth
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.planners import BuiltInPlanner
from google.adk.plugins import LoggingPlugin
from google.genai import types

from .tools import (
    compare_versions,
    count_failures,
    create_evolution_issue,
    create_evolution_pr,
    extract_regression_cases,
    detect_bottleneck_tool,
    download_from_gcs,
    extract_eval_cases,
    list_agents,
    parse_quality_issue,
    push_skill_to_registry,
    read_current_eval_cases,
    read_skill,
    restore_skills,
    run_coevolution,
    run_evolution,
    run_quality_report,
    score_candidate,
    snapshot_skills,
    upload_run_to_gcs,
)

# Load .env from project root if it exists
env_path = os.path.join(os.path.dirname(__file__), "../../../.env")
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)

_, project_id = google.auth.default()

MODEL_ID = os.getenv("SKILL_EVOLUTION_MODEL_ID", "gemini-2.5-pro")

os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
os.environ["GOOGLE_CLOUD_PROJECT"] = os.getenv("PROJECT_ID", project_id or "")
os.environ["GOOGLE_CLOUD_LOCATION"] = os.getenv("REGION", "us-central1")

# Load instruction from SKILL.md + references/
_skill_dir = os.path.join(os.path.dirname(__file__), "skill")
try:
    from agents.enterprise.policy_agent.skill_loader import load_skill
    INSTRUCTION = load_skill(_skill_dir)
except Exception:
    # Fallback if skill_loader or SKILL.md not available
    INSTRUCTION = "You are a Skill Evolution Agent. Use the provided tools to analyze agent quality and evolve agent skills."

SHOW_THOUGHTS = os.getenv("SHOW_THOUGHTS", "true").lower() in ("true", "1", "yes")

root_agent = Agent(
    name="skill_evolution_agent",
    model=Gemini(
        model=MODEL_ID,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description=(
        "Analyzes agent quality reports and evolves agent skills through "
        "trajectory analysis, parallel analyst fleets, and patch "
        "consolidation. Extracts failed conversations as regression tests."
    ),
    instruction=INSTRUCTION,
    planner=BuiltInPlanner(
        thinking_config=types.ThinkingConfig(include_thoughts=SHOW_THOUGHTS),
    ),
    tools=[
        parse_quality_issue,
        run_quality_report,
        detect_bottleneck_tool,
        run_evolution,
        run_coevolution,
        extract_eval_cases,
        read_current_eval_cases,
        upload_run_to_gcs,
        download_from_gcs,
        create_evolution_issue,
        push_skill_to_registry,
        extract_regression_cases,
        create_evolution_pr,
        snapshot_skills,
        restore_skills,
        count_failures,
        score_candidate,
        read_skill,
        list_agents,
        compare_versions,
    ],
)

app = App(
    root_agent=root_agent,
    name="skill_evolution_agent",
    plugins=[LoggingPlugin()],
)
