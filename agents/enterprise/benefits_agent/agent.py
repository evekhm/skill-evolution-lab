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

"""Company Benefits agent -- A2A sub-agent for the Knowledge Supervisor.

Mirrors the policy agent's serving structure: Cloud Run service behind
an A2A endpoint, skill loaded from the Skill Registry at startup
(SKILL_SOURCE=registry), conversations logged to BigQuery. The shared
modules tools.py and skill_loader.py are copied in from policy_agent at
deploy time (same pattern as skill_registry.py) so there is exactly one
source of truth for them in the repository.
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

from .tools import get_current_date, lookup_benefits, search_hr_handbook

env_path = os.path.join(os.path.dirname(__file__), "../../../.env")
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)

_, project_id = google.auth.default()

MODEL_ID = os.getenv("BENEFITS_AGENT_MODEL_ID", "gemini-3.5-flash")

import logging as _logging
_logger = _logging.getLogger(__name__)

from .skill_loader import load_skill, load_skill_metadata
_skill_dir = os.path.join(os.path.dirname(__file__), "skill")
try:
    CURRENT_PROMPT = load_skill(_skill_dir)
    _logger.info("Loaded skill-evolution prompt from %s", _skill_dir)
except Exception as _e:
    _logger.error("Failed to load skill, using fallback instruction: %s", _e)
    CURRENT_PROMPT = "You help employees with questions about company benefits."

DATASET_ID = os.getenv('DATASET_ID')
DATASET_LOCATION = os.getenv('DATASET_LOCATION')
TABLE_ID = os.getenv('TABLE_ID')

os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
os.environ["GOOGLE_CLOUD_PROJECT"] = os.getenv("PROJECT_ID", project_id or "")
os.environ["GOOGLE_CLOUD_LOCATION"] = (
    os.getenv("MODEL_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "global"
)  # model endpoint, not infra region: gemini-3.x is global-only

print(f"--- Benefits Agent ---")
print(f"DATASET_ID: {DATASET_ID}")
print(f"DATASET_LOCATION: {DATASET_LOCATION}")
print(f"TABLE_ID: {TABLE_ID}")
print(f"GOOGLE_CLOUD_PROJECT: {os.environ.get('GOOGLE_CLOUD_PROJECT')}")
print(f"GOOGLE_CLOUD_LOCATION: {os.environ.get('GOOGLE_CLOUD_LOCATION')}")
print(f"------------------------------------------")

AGENT_TOOLS = [lookup_benefits, search_hr_handbook, get_current_date]


def create_agent(prompt: str = CURRENT_PROMPT, model_id: str | None = None) -> Agent:
    """Create a company benefits agent with the given prompt."""
    return Agent(
        name="benefits_agent",
        model=Gemini(
            model=model_id or MODEL_ID,
            retry_options=types.HttpRetryOptions(attempts=3),
        ),
        description=(
            "Handles EMPLOYEE BENEFITS questions: health/dental/vision "
            "insurance, HSA, orthodontia, max out-of-pocket, 401k/retirement, "
            "parental and adoption leave, benefits enrollment, the employee "
            "assistance program (EAP), tuition reimbursement, and short-term "
            "disability. Does NOT handle time-off/workplace policies (PTO, "
            "sick leave, remote work, expenses, holidays, bereavement, jury "
            "duty, flex time) -- route those to policy_agent."
        ),
        instruction=prompt,
        tools=AGENT_TOOLS,
    )


root_agent = create_agent()

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
    name="benefits_agent",
    plugins=[bq_logging_plugin, LoggingPlugin()],
)
