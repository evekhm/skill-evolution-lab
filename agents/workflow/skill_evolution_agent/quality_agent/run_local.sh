#!/bin/bash
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

# Run the Quality Agent locally.
#
# Usage:
#   ./agents/workflow/quality_agent/run_local.sh                    # interactive via adk web
#   ./agents/workflow/quality_agent/run_local.sh --test             # test tools only (no agent)
#   ./agents/workflow/quality_agent/run_local.sh --test 1h          # test with custom time period
#   ./agents/workflow/quality_agent/run_local.sh --period 6h        # one-shot: run report + create GitHub issues
#   ./agents/workflow/quality_agent/run_local.sh --period 1d        # one-shot: last 24 hours
#   ./agents/workflow/quality_agent/run_local.sh --dry-run          # write issues as local .md files (no GitHub)
#   ./agents/workflow/quality_agent/run_local.sh --dry-run --period 1d
#
# Dry-run mode writes issue markdown files to eval/runs/<timestamp>_quality/issues/
# instead of creating real GitHub issues. Use this to inspect what the agent would
# create before running it for real.
#
# Output:
#   eval/runs/<timestamp>_quality/
#     quality_report.json   — full quality report (sessions, scores, summary)
#     issues/               — (dry-run only) one .md file per issue
#
# Prerequisites:
#   - .env configured with PROJECT_ID, DATASET_ID, TABLE_ID, DATASET_LOCATION
#   - GITHUB_TOKEN set (or github-pat secret in Secret Manager)
#   - bigquery-agent-analytics SDK installed

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Load .env
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
else
    echo "ERROR: .env not found at $PROJECT_ROOT/.env"
    exit 1
fi

# Validate required env vars
for var in PROJECT_ID DATASET_ID TABLE_ID DATASET_LOCATION; do
    if [ -z "${!var}" ]; then
        echo "ERROR: $var is not set in .env"
        exit 1
    fi
done

# Auto-detect GITHUB_REPO from git remote if not set
if [ -z "$GITHUB_REPO" ]; then
    GITHUB_REPO=$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null \
        | sed 's|.*github.com[:/]\(.*\)\.git|\1|' || echo "")
    if [ -n "$GITHUB_REPO" ]; then
        export GITHUB_REPO
    fi
fi

echo "========================================="
echo "  Quality Agent"
echo "========================================="
echo "  Project:    $PROJECT_ID"
echo "  Dataset:    $DATASET_ID.$TABLE_ID"
echo "  Location:   $DATASET_LOCATION"
echo "  GitHub:     ${GITHUB_REPO:-not configured}"
echo "  GitHub Token: $([ -n "$GITHUB_TOKEN" ] && echo 'set (env)' || echo 'will use Secret Manager')"
# Check if --dry-run is in the args
DRY_RUN_MSG=""
for arg in "$@"; do
    if [ "$arg" = "--dry-run" ]; then
        DRY_RUN_MSG="  Mode:       DRY RUN (no GitHub issues — output to dry_run_output/)"
        break
    fi
done
if [ -n "$DRY_RUN_MSG" ]; then
    echo "$DRY_RUN_MSG"
fi
echo "========================================="
echo ""

# If no args or --test/--period, run the Python runner
if [ $# -eq 0 ]; then
    echo "Starting ADK web UI..."
    echo "Open http://localhost:8000 in your browser."
    echo ""
    uv run adk web "$SCRIPT_DIR"
else
    cd "$PROJECT_ROOT"
    uv run python3 agents/workflow/quality_agent/main.py "$@"
fi
