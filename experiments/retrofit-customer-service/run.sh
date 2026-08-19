#!/usr/bin/env bash
# Wrapper: sources .env, forwards all args to runner.py.
set -euo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a
exec uv run python runner.py "$@"
