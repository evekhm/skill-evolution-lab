FROM python:3.11-slim

WORKDIR /app

# Install git and curl (curl needed for agy installer)
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI (gh) for PR creation
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*

# Install Antigravity CLI (agy) for PR creation
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash
ENV PATH="/root/.local/bin:${PATH}"

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Clone the SDK (score_conversations.py delegates to it via ensure_sdk).
# SDK_REPO/SDK_BRANCH come from .env via deploy.sh (no values defined here).
ARG SDK_REPO
ARG SDK_BRANCH
RUN test -n "${SDK_REPO}" && test -n "${SDK_BRANCH}" \
    || (echo "ERROR: SDK_REPO and SDK_BRANCH build args are required (deploy.sh passes them from .env)" && false)
RUN git clone --depth 1 --branch ${SDK_BRANCH} ${SDK_REPO} /sdk
ENV SDK_DIR=/sdk

# Copy ensure_sdk.py (copied into build context by deploy.sh)
COPY ensure_sdk.py .

# Copy shared eval module (copied into build context by deploy.sh)
COPY eval ./eval

# Copy traffic generator (copied into build context by deploy.sh)
COPY traffic_generator ./agents/workflow/traffic_generator

# Copy enterprise agents for local mode (copied into build context by deploy.sh)
COPY enterprise ./agents/enterprise

# Copy quality agent (QUALITY_SOURCE=bigquery pre-flight reuses its
# run_quality_report; copied into build context by deploy.sh)
COPY quality_agent ./agents/workflow/quality_agent

# Copy shared utilities (copied into build context by deploy.sh)
COPY gcs_utils.py ./agents/workflow/gcs_utils.py

# Copy agent code preserving package structure
# All pipeline files (evolve.py, bottleneck.py, etc.) live inside the agent
COPY . ./agents/workflow/skill_evolution_agent
RUN touch ./agents/__init__.py ./agents/workflow/__init__.py

# Set working directory
WORKDIR /app/agents/workflow/skill_evolution_agent

# Set python path to include project root
ENV PYTHONPATH=/app

ENTRYPOINT ["python", "main.py"]
