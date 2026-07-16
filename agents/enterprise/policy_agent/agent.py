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

"""Company Policy agent -- A2A sub-agent for the Knowledge Supervisor.

This is the same agent from the blog post "Your Agent Can Fix Its Own
Prompt", now deployed as a standalone Cloud Run service with an A2A
endpoint.  The supervisor routes policy questions here.
"""

import os

import google.auth
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.plugins import LoggingPlugin
from google.adk.plugins.bigquery_agent_analytics_plugin import (
    BigQueryAgentAnalyticsPlugin,
    BigQueryLoggerConfig,
)
from google.genai import types

from .tools import get_current_date, lookup_company_policy, lookup_benefits, search_hr_handbook

# Load .env from project root if it exists
env_path = os.path.join(os.path.dirname(__file__), "../../../.env")
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)

_, project_id = google.auth.default()

MODEL_ID = os.getenv("POLICY_AGENT_MODEL_ID", "gemini-2.5-flash")

# Load prompt: skill-evolution SKILL.md > Vertex AI Prompt Manager > local prompts.py
import logging as _logging
_logger = _logging.getLogger(__name__)

_prompt_mode = os.getenv("PROMPT_MODE", "skill-evolution").lower()

if _prompt_mode == "skill-evolution":
    # Skill Evolution: load from SKILL.md directory
    from .skill_loader import load_skill
    _skill_dir = os.path.join(os.path.dirname(__file__), "skill")
    try:
        CURRENT_PROMPT = load_skill(_skill_dir)
        _logger.info("Loaded skill-evolution prompt from %s", _skill_dir)
    except Exception as _e:
        _logger.error("Failed to load skill, falling back to prompts.py: %s", _e)
        from .prompts import CURRENT_PROMPT
else:
    # Reactive Loop: Vertex AI Prompt Manager or local prompts.py
    _policy_prompt_id = os.getenv("POLICY_VERTEX_PROMPT_ID")

    if _policy_prompt_id:
        from vertexai import Client as _VertexClient
        _vx_client = _VertexClient(
            project=os.getenv("PROJECT_ID", project_id or ""),
            location=os.getenv("REGION", "us-central1"),
        )
        try:
            _prompt_obj = _vx_client.prompts.get(prompt_id=_policy_prompt_id)
            CURRENT_PROMPT = _prompt_obj.prompt_data.system_instruction.parts[0].text or ""
            _logger.info("Loaded policy prompt from Vertex AI (%s)", _policy_prompt_id)
        except Exception as _e:
            _logger.warning("Failed to load from Vertex AI, falling back to local: %s", _e)
            from .prompts import CURRENT_PROMPT
    else:
        _logger.info("Using local prompts.py (POLICY_VERTEX_PROMPT_ID not set)")
        from .prompts import CURRENT_PROMPT

# Big Query
DATASET_ID = os.getenv('DATASET_ID')
DATASET_LOCATION = os.getenv('DATASET_LOCATION')
TABLE_ID = os.getenv('TABLE_ID')

os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
os.environ["GOOGLE_CLOUD_PROJECT"] = os.getenv("PROJECT_ID", project_id or "")
os.environ["GOOGLE_CLOUD_LOCATION"] = os.getenv("REGION", "us-central1")

print(f"--- Policy Agent ---")
print(f"DATASET_ID: {DATASET_ID}")
print(f"DATASET_LOCATION: {DATASET_LOCATION}")
print(f"TABLE_ID: {TABLE_ID}")
print(f"GOOGLE_CLOUD_PROJECT: {os.environ.get('GOOGLE_CLOUD_PROJECT')}")
print(f"GOOGLE_CLOUD_LOCATION: {os.environ.get('GOOGLE_CLOUD_LOCATION')}")
print(f"------------------------------------------")

AGENT_TOOLS = [lookup_company_policy, search_hr_handbook, get_current_date]
# Single-agent skill-extraction lab: give the standalone policy agent the
# benefits lookup too, so it can answer benefits questions (parental leave, 401k,
# dental, HSA...). The flawed V0 prompt then fails on them for a SKILL reason
# (it defers despite having the tool), not a missing-capability reason. Opt-in so
# the multi-agent demo's domain split is unaffected.
if os.getenv("POLICY_AGENT_INCLUDE_BENEFITS") == "1":
    AGENT_TOOLS = [lookup_company_policy, lookup_benefits, search_hr_handbook, get_current_date]


def create_agent(prompt: str = CURRENT_PROMPT, model_id: str | None = None) -> Agent:
    """Create a company policy agent with the given prompt."""
    return Agent(
        name="policy_agent",
        model=Gemini(
            model=model_id or MODEL_ID,
            retry_options=types.HttpRetryOptions(attempts=3),
        ),
        description=(
            "Handles TIME-OFF and WORKPLACE policy questions: PTO, sick leave, "
            "remote work, expenses, holidays, bereavement leave, jury duty, and "
            "flex time. Does NOT handle benefits (insurance, 401k, parental "
            "leave, EAP, tuition, disability) -- route those to benefits_agent."
        ),
        instruction=prompt,
        tools=AGENT_TOOLS,
    )


root_agent = create_agent()

from .skill_loader import load_skill_metadata
_skill_meta = load_skill_metadata(os.path.join(os.path.dirname(__file__), "skill"))
_agent_version = os.getenv("AGENT_VERSION") or _skill_meta.get("metadata", {}).get("version", "unknown")

bq_config = BigQueryLoggerConfig(
    enabled=True,
    max_content_length=500 * 1024,
    batch_size=1,
    shutdown_timeout=10.0,
    custom_tags={"agent_version": _agent_version},
)
bq_logging_plugin = BigQueryAgentAnalyticsPlugin(
    project_id=project_id,
    dataset_id=DATASET_ID,
    table_id=TABLE_ID,
    config=bq_config,
    location=DATASET_LOCATION,
)
app = App(
    root_agent=root_agent,
    name="policy_agent",
    plugins=[bq_logging_plugin, LoggingPlugin()],
)
