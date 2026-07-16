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

import logging
import os
import sys

from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.plugins import LoggingPlugin
from google.genai import types
from google.genai import Client


# Workaround for ADK event loop bug in multi-threaded Agent Engine.
# Gemini's @cached_property binds the aiohttp session to the first request's
# event loop; subsequent requests on a new loop get "Event loop is closed".
# This forces a fresh Client per access. Remove once google/adk-python#5543 lands.
# See: https://github.com/google/adk-python/issues/5538
class _UncachedGemini(Gemini):
    @property
    def api_client(self) -> Client:
        kwargs = {
            "http_options": types.HttpOptions(
                headers=self._tracking_headers(),
                retry_options=self.retry_options,
                base_url=self.base_url,
            )
        }
        if self.model.startswith("projects/"):
            kwargs["vertexai"] = True
        return Client(**kwargs)

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
import httpx
import google.auth
import google.auth.transport.requests
import google.oauth2.id_token
import json

from .config import (
    discover_policy_agent_url,
    discover_hr_calculator_url,
    discover_benefits_agent_url,
    SUPERVISOR_DISPLAY_NAME,
    MODEL_ID,
    PROJECT_ID,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# -- Cloud Run authentication for A2A calls --


class CloudRunAuth(httpx.Auth):

    def __init__(self, audience: str):
        self.audience = audience
        self.auth_req = google.auth.transport.requests.Request()

    def auth_flow(self, request):
        logger.info(f"CloudRunAuth: Attempting to get auth token for {self.audience}")
        env_token = os.getenv("A2A_ID_TOKEN")
        if env_token:
            logger.info(
                "CloudRunAuth: Using token from environment variable A2A_ID_TOKEN"
            )
            token = env_token
        else:
            try:
                logger.info(
                    "CloudRunAuth: Fetching ID token via google.oauth2.id_token"
                )
                token = google.oauth2.id_token.fetch_id_token(
                    self.auth_req, self.audience
                )
            except Exception as e:
                logger.warning(
                    f"CloudRunAuth: Failed to fetch ID token via SDK: {e}. Trying gcloud..."
                )
                try:
                    import subprocess

                    result = subprocess.run(
                        ["gcloud", "auth", "print-identity-token", "--quiet"],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    token = result.stdout.strip()
                    logger.info("CloudRunAuth: Successfully fetched token via gcloud")
                except Exception as e2:
                    logger.error(
                        f"CloudRunAuth: Failed to fetch ID token via gcloud: {e2}"
                    )
                    raise Exception(
                        f"Failed to fetch ID token via SDK and gcloud: {e2}"
                    )
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


class CardInterceptClient(httpx.AsyncClient):
    """Rewrites the agent card URL to point at the correct A2A path."""

    def __init__(self, server_url, agent_name, **kwargs):
        super().__init__(**kwargs)
        self.server_url = server_url
        self.agent_name = agent_name

    async def request(self, method, url, **kwargs):
        logger.info(f"CardInterceptClient: Request {method} {url}")
        response = await super().request(method, url, **kwargs)
        if method == "GET" and "/.well-known/agent-card.json" in str(url):
            logger.info("CardInterceptClient: Intercepting agent card request")
            try:
                data = response.json()
                logger.info(
                    f"CardInterceptClient: Original card data URL: {data.get('url')}"
                )
                data["url"] = f"{self.server_url}/a2a/{self.agent_name}"
                content = json.dumps(data).encode("utf-8")
                response = httpx.Response(
                    status_code=response.status_code,
                    headers=response.headers,
                    content=content,
                    request=response.request,
                )
                logger.info(
                    f"CardInterceptClient: Overwrote card URL to: {data['url']}"
                )
            except Exception as e:
                logger.error(f"CardInterceptClient: Failed to modify card: {e}")
                pass
        return response


def _create_remote_agent(name, description, url, agent_path_name=None):
    """Create a RemoteA2aAgent with Cloud Run auth if needed."""
    agent_path_name = agent_path_name or name
    auth = None
    if url.startswith("https://"):
        auth = CloudRunAuth(audience=url)

    http_client = CardInterceptClient(
        server_url=url,
        agent_name=agent_path_name,
        auth=auth,
        timeout=60.0,
    )

    return RemoteA2aAgent(
        name=name,
        description=description,
        agent_card=f"{url}/a2a/{agent_path_name}/.well-known/agent-card.json",
        httpx_client=http_client,
    )


# -- Discover sub-agent URLs --

policy_agent_url = discover_policy_agent_url()
logger.info(f"Policy agent URL: {policy_agent_url}")

hr_calculator_url = discover_hr_calculator_url()
logger.info(f"HR Calculator URL: {hr_calculator_url}")

# -- Create remote A2A agents --

policy_remote_agent = _create_remote_agent(
    name="policy_agent",
    description=(
        "Answers questions about company policies including PTO, sick leave, "
        "remote work, expenses, benefits, holidays, and current date. "
        "Route ANY question about company policies, HR procedures, time off rules, "
        "vacation policy, leave policy, reimbursement rules, or employee benefits here."
    ),
    url=policy_agent_url,
)

hr_calculator_remote_agent = _create_remote_agent(
    name="hr_calculator",
    description=(
        "A remote agent that calculates PTO balances, sick leave balances, "
        "working days for specific date ranges, and remaining work days in a "
        "month/quarter/year."
    ),
    url=hr_calculator_url,
)

# Benefits specialist -- only wired if a service is deployed (URL discoverable).
# Mirrors the demo's 3-agent split; degrades gracefully when absent.
benefits_agent_url = discover_benefits_agent_url()
benefits_remote_agent = None
if benefits_agent_url:
    logger.info(f"Benefits agent URL: {benefits_agent_url}")
    benefits_remote_agent = _create_remote_agent(
        name="benefits_agent",
        description=(
            "Handles EMPLOYEE BENEFITS questions: health/dental/vision insurance, "
            "HSA, 401k/retirement, parental and adoption leave, benefits "
            "enrollment, EAP, tuition reimbursement, and short-term disability."
        ),
        url=benefits_agent_url,
    )
else:
    logger.warning(
        "No benefits service discovered (BENEFITS_AGENT_URL unset); supervisor "
        "will run without a benefits tool. Deploy benefits-agent for full parity."
    )

# -- Supervisor Prompt --
# Load from Vertex AI Prompt Manager if SUPERVISOR_VERTEX_PROMPT_ID is set,
# otherwise fall back to local prompts.py.

_prompt_mode = os.getenv("PROMPT_MODE", "skill-evolution").lower()
_supervisor_prompt_id = os.getenv("SUPERVISOR_VERTEX_PROMPT_ID")

if _prompt_mode == "skill-evolution":
    # Skill Evolution: the supervisor's instruction IS its SKILL.md, so routing
    # behaviour is evolvable just like the policy agent's.
    # Local-first: deploy.sh copies skill_loader.py into app/ because the
    # Agent Engine package contains only app/ (the cross-package import cannot
    # resolve there).
    try:
        from .skill_loader import load_skill
    except ImportError:
        from agents.enterprise.policy_agent.skill_loader import load_skill
    _sup_skill_dir = os.path.join(os.path.dirname(__file__), "skill")
    try:
        _supervisor_instruction = load_skill(_sup_skill_dir)
        logger.info("Loaded supervisor skill-evolution prompt from %s", _sup_skill_dir)
    except Exception as _e:
        logger.error("Failed to load supervisor skill, falling back to prompts.py: %s", _e)
        from .prompts import SUPERVISOR_INSTRUCTION
        _supervisor_instruction = SUPERVISOR_INSTRUCTION
elif _supervisor_prompt_id:
    from vertexai import Client as _VertexClient
    _vx_client = _VertexClient(project=PROJECT_ID, location=os.getenv("REGION", "us-central1"))
    try:
        _prompt_obj = _vx_client.prompts.get(prompt_id=_supervisor_prompt_id)
        _supervisor_instruction = _prompt_obj.prompt_data.system_instruction.parts[0].text or ""
        logger.info("Loaded supervisor prompt from Vertex AI (%s)", _supervisor_prompt_id)
    except Exception as _e:
        logger.warning("Failed to load from Vertex AI, falling back to local: %s", _e)
        from .prompts import SUPERVISOR_INSTRUCTION
        _supervisor_instruction = SUPERVISOR_INSTRUCTION
else:
    logger.info("Using local prompts.py (SUPERVISOR_VERTEX_PROMPT_ID not set)")
    from .prompts import SUPERVISOR_INSTRUCTION
    _supervisor_instruction = SUPERVISOR_INSTRUCTION

# AgentTool (not sub_agents): the supervisor invokes each specialist as a tool,
# gets the result back, and can call MULTIPLE specialists in one turn then
# synthesize -- required for compound cross-domain questions. The handoff model
# (sub_agents) ends the turn on transfer and cannot do this. Mirrors the demo's
# _build_local_supervisor so the deployed agent has parity with what was evaluated.
from google.adk.tools import AgentTool

_specialists = [policy_remote_agent, hr_calculator_remote_agent]
if benefits_remote_agent is not None:
    _specialists.append(benefits_remote_agent)

supervisor_agent = Agent(
    name="knowledge_supervisor",
    model=_UncachedGemini(
        model=MODEL_ID,
        retry_options=types.HttpRetryOptions(attempts=5),
    ),
    description=(
        "Answers employee questions about company policies, PTO, sick leave, "
        "remote work, expenses, benefits, holidays, and HR calculations."
    ),
    instruction=_supervisor_instruction,
    tools=[AgentTool(a) for a in _specialists],
)


# -- BigQuery Agent Analytics Plugin --

from google.adk.plugins.bigquery_agent_analytics_plugin import BigQueryLoggerConfig, BigQueryAgentAnalyticsPlugin
from .config import project_id, DATASET_ID, DATASET_LOCATION, TABLE_ID
try:
    from .skill_loader import load_skill_metadata
except ImportError:
    from agents.enterprise.policy_agent.skill_loader import load_skill_metadata

_skill_dir = os.path.join(os.path.dirname(__file__), "skill")
_skill_meta = load_skill_metadata(_skill_dir)
_agent_version = os.getenv("AGENT_VERSION") or _skill_meta.get("metadata", {}).get("version", "unknown")

bq_config = BigQueryLoggerConfig(
    enabled=True, max_content_length=500 * 1024, batch_size=1, shutdown_timeout=10.0,
    custom_tags={"agent_version": _agent_version},
)
bq_logging_plugin = BigQueryAgentAnalyticsPlugin(
    project_id=project_id,
    dataset_id=DATASET_ID,
    table_id=TABLE_ID,
    config=bq_config,
    location=DATASET_LOCATION,
)


# -- ADK App --
# ADK wraps this in AdkApp during `adk deploy agent_engine`, which
# exposes stream_query via :streamQuery (used by Gemini Enterprise).

# The Reasoning Engine display name is hyphenated (knowledge-supervisor),
# but an ADK App name must be a valid Python identifier — sanitize it.
app = App(
    root_agent=supervisor_agent,
    name=SUPERVISOR_DISPLAY_NAME.replace("-", "_"),
    plugins=[bq_logging_plugin, LoggingPlugin()],
)

adk_app = app

# Export for `adk web` (needs a root_agent at module level)
root_agent = supervisor_agent
