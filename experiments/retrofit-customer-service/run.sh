#!/usr/bin/env bash
# Wrapper: sources .env, forwards all args to runner.py.
#
# Run this from the harness directory built in README step 2 (uv project
# with the customer-service sample installed), with the archive files
# copied in. Running it in place inside the repo resolves the repo's own
# uv project, which does not carry the sample (review R7-2 on PR #107).
set -euo pipefail
cd "$(dirname "$0")"
set -a; source .env; set +a
if ! uv run python -c "import customer_service" >/dev/null 2>&1; then
    echo "run.sh: the resolved uv project cannot import 'customer_service'." >&2
    echo "Build the harness project first (README step 2):" >&2
    echo "  uv init --bare; uv add --editable <clone>/python/agents/customer-service \\" >&2
    echo "      \"google-adk[bigquery-analytics]==1.32.0\" google-cloud-bigquery-storage" >&2
    echo "then copy this archive's runner.py, run.sh, questions_*.json," >&2
    echo "cs_eval_spec.json and .env into that directory and rerun." >&2
    exit 1
fi
exec uv run python runner.py "$@"
