FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code
COPY . .

# ADK A2A server on port 8080
EXPOSE 8080
CMD ["adk", "api_server", "--port", "8080", "--agent_dir", "."]
