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

import os
import google.auth
from dotenv import load_dotenv
import subprocess
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

env_path = os.path.join(os.path.dirname(__file__), "../../../../.env")
if os.path.exists(env_path):
    logger.info(f"Loading .env from {env_path}")
    load_dotenv(dotenv_path=env_path, override=False)
else:
    logger.info(f".env not found at {env_path}, relying on environment variables.")

_, project_id = google.auth.default()

PROJECT_ID = os.getenv('PROJECT_ID', project_id)
REGION = os.getenv('SUPERVISOR_REGION', 'us-central1')
MODEL_ID = os.getenv('SUPERVISOR_MODEL_ID', 'gemini-2.5-pro')
SUPERVISOR_DISPLAY_NAME = os.getenv('SUPERVISOR_DISPLAY_NAME', "HR Policy Assistant")

# A2A Sub-Agent URLs
POLICY_AGENT_URL = os.getenv('POLICY_AGENT_URL')
POLICY_AGENT_SERVICE_NAME = os.getenv('POLICY_AGENT_SERVICE_NAME', "policy-agent")

HR_CALCULATOR_URL = os.getenv('HR_CALCULATOR_URL')
HR_CALCULATOR_SERVICE_NAME = os.getenv('HR_CALCULATOR_SERVICE_NAME', "hr-calculator")

# Benefits specialist (optional). Mirrors the demo's 3-agent split. Only wired
# into the supervisor when a URL is configured/discoverable -- there may be no
# deployed benefits service yet, and the supervisor must still start without it.
BENEFITS_AGENT_URL = os.getenv('BENEFITS_AGENT_URL')
BENEFITS_AGENT_SERVICE_NAME = os.getenv('BENEFITS_AGENT_SERVICE_NAME', "benefits-agent")

os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = REGION
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

# Big Query (for BQ Analytics Plugin logging)
DATASET_ID = os.getenv('DATASET_ID')
DATASET_LOCATION = os.getenv('DATASET_LOCATION')
TABLE_ID = os.getenv('TABLE_ID')

logger.info(f"Loaded config: SUPERVISOR_MODEL_ID={MODEL_ID}, SUPERVISOR_DISPLAY_NAME={SUPERVISOR_DISPLAY_NAME}")
logger.info(f"Loaded config: POLICY_AGENT_URL={POLICY_AGENT_URL}, HR_CALCULATOR_URL={HR_CALCULATOR_URL}")
logger.info(f"Loaded config: DATASET_ID={DATASET_ID}, DATASET_LOCATION={DATASET_LOCATION}, TABLE_ID={TABLE_ID}")


def _discover_cloud_run_url(service_name: str, region: str = None) -> str:
    """Discovers a Cloud Run service URL using gcloud."""
    region = region or REGION
    cmd = [
        "gcloud", "run", "services", "describe", service_name,
        f"--project={PROJECT_ID}",
        f"--region={region}",
        "--format=value(status.url)"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        discovered_url = result.stdout.strip()
        if discovered_url:
            return discovered_url
    except Exception as e:
        logger.warning(f"Could not discover {service_name}: {e}")
    return None


def discover_policy_agent_url() -> str:
    """Discovers the policy_agent URL using .env fallback to Cloud Run."""
    if POLICY_AGENT_URL:
        return POLICY_AGENT_URL
    url = _discover_cloud_run_url(POLICY_AGENT_SERVICE_NAME)
    if url:
        os.environ['POLICY_AGENT_URL'] = url
        return url
    return "http://localhost:8080"


def discover_hr_calculator_url() -> str:
    """Discovers the hr_calculator URL using .env fallback to Cloud Run."""
    if HR_CALCULATOR_URL:
        return HR_CALCULATOR_URL
    url = _discover_cloud_run_url(HR_CALCULATOR_SERVICE_NAME)
    if url:
        os.environ['HR_CALCULATOR_URL'] = url
        return url
    return "http://localhost:8081"


def discover_benefits_agent_url() -> str | None:
    """Discover the benefits_agent URL, or None if no service is configured.

    Unlike policy/hr, this returns None (not a localhost default) when nothing is
    found, so the supervisor can omit the benefits tool gracefully when no
    benefits service has been deployed yet.
    """
    if BENEFITS_AGENT_URL:
        return BENEFITS_AGENT_URL
    url = _discover_cloud_run_url(BENEFITS_AGENT_SERVICE_NAME)
    if url:
        os.environ['BENEFITS_AGENT_URL'] = url
        return url
    return None
