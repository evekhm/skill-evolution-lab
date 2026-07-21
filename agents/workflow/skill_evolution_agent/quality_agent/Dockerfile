FROM python:3.11-slim

WORKDIR /app

# Install git, curl (for agy installer), and gh CLI
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI (gh) for issue creation
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*

# Install Antigravity CLI (agy) for rich issue body generation (optional)
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash || true
ENV PATH="/root/.local/bin:${PATH}"

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Clone the SDK (quality_report.py delegates to it via ensure_sdk).
# SDK_REPO/SDK_BRANCH come from .env via deploy.sh (no values defined here).
ARG SDK_REPO
ARG SDK_BRANCH
RUN test -n "${SDK_REPO}" && test -n "${SDK_BRANCH}" \
    || (echo "ERROR: SDK_REPO and SDK_BRANCH build args are required (deploy.sh passes them from .env)" && false)
RUN git clone --depth 1 --branch ${SDK_BRANCH} ${SDK_REPO} /sdk
ENV SDK_DIR=/sdk

# Copy ensure_sdk.py (copied into build context by deploy.sh)
COPY ensure_sdk.py .

# Copy shared utilities (copied into build context by deploy.sh)
COPY gcs_utils.py ./agents/workflow/gcs_utils.py

# Copy agent code preserving package structure
COPY . ./agents/workflow/quality_agent
RUN touch ./agents/__init__.py ./agents/workflow/__init__.py

# Set working directory
WORKDIR /app/agents/workflow/quality_agent

# Set python path to include project root
ENV PYTHONPATH=/app

ENTRYPOINT ["python", "main.py"]
