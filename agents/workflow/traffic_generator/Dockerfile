FROM python:3.11-slim

WORKDIR /app

# Install git (needed for pip git+ dependencies)
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code
COPY . ./agents/load_test_agent

# Set working directory
WORKDIR /app/agents/load_test_agent

# Set python path to include project root
ENV PYTHONPATH=/app

# Run the job driver
ENTRYPOINT ["python", "main.py"]
