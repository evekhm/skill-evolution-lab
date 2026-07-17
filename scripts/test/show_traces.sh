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

# show_traces.sh — inspect the BigQuery traces the evolution loop sees.
#
# Modes:
#   bash scripts/test/show_traces.sh              # label distribution (all traffic)
#   bash scripts/test/show_traces.sh --selector   # preview EXACTLY what the
#                                                 # evolution pre-flight would fetch
#                                                 # with the current env selector
#
# Selector env (same variables the evolution job reads):
#   EVAL_TIME_PERIOD          window, e.g. 6h / 24h / 7d   (default 6h)
#   AGENT_VERSION             skill version filter          (default: any)
#   QUALITY_APP_NAME          root agent app                (default knowledge_supervisor)
#   EVOLUTION_TRACE_LABELS    k=v,k2=v2 custom_tags filter  (default: none)
#
# Examples:
#   EVOLUTION_TRACE_LABELS=run_id=20260716-233051 bash scripts/test/show_traces.sh --selector
#   EVAL_TIME_PERIOD=24h AGENT_VERSION=0 bash scripts/test/show_traces.sh --selector

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
set -a
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/.env"
set +a

TABLE="\`${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}\`"
MODE="${1:-summary}"

if [ "${MODE}" = "--selector" ]; then
    PERIOD="${EVAL_TIME_PERIOD:-6h}"
    APP="${QUALITY_APP_NAME:-knowledge_supervisor}"
    VERSION="${AGENT_VERSION:-}"

    # Window: 6h/24h -> hours, 7d -> days
    case "${PERIOD}" in
        *h) INTERVAL="INTERVAL ${PERIOD%h} HOUR" ;;
        *d) INTERVAL="INTERVAL ${PERIOD%d} DAY" ;;
        *)  INTERVAL="INTERVAL 6 HOUR" ;;
    esac

    WHERE="timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), ${INTERVAL})"
    WHERE="${WHERE} AND agent = '${APP}'"
    if [ -n "${VERSION}" ]; then
        WHERE="${WHERE} AND JSON_VALUE(attributes, '\$.custom_tags.agent_version') = '${VERSION}'"
    fi
    # Label filters: k=v,k2=v2
    IFS=',' read -ra PAIRS <<< "${EVOLUTION_TRACE_LABELS:-}"
    for pair in "${PAIRS[@]:-}"; do
        [ -z "${pair}" ] && continue
        key="${pair%%=*}"; val="${pair#*=}"
        WHERE="${WHERE} AND JSON_VALUE(attributes, '\$.custom_tags.${key}') = '${val}'"
    done

    echo "=== Evolution pre-flight selector preview ==="
    echo "window=${PERIOD}  app=${APP}  version=${VERSION:-any}  labels=${EVOLUTION_TRACE_LABELS:-none}"
    echo ""
    bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --format=pretty \
      "SELECT COUNT(DISTINCT session_id) AS sessions, COUNT(*) AS events,
              MIN(timestamp) AS earliest, MAX(timestamp) AS latest
       FROM ${TABLE} WHERE ${WHERE}"
    echo ""
    echo "=== Sample sessions (up to 10) ==="
    bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --format=pretty \
      "SELECT session_id,
              MIN(timestamp) AS started,
              COUNT(*) AS events,
              ANY_VALUE(JSON_VALUE(attributes, '\$.custom_tags.run_id')) AS run_id
       FROM ${TABLE} WHERE ${WHERE}
       GROUP BY session_id ORDER BY started DESC LIMIT 10"
else
    echo "=== Label distribution (all traffic, by sessions) ==="
    bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --format=pretty \
      "SELECT
         JSON_VALUE(attributes, '\$.custom_tags.agent_version') AS agent_version,
         JSON_VALUE(attributes, '\$.custom_tags.sw_version')    AS sw_version,
         JSON_VALUE(attributes, '\$.custom_tags.traffic_source') AS traffic_source,
         JSON_VALUE(attributes, '\$.custom_tags.run_id')        AS run_id,
         agent,
         COUNT(DISTINCT session_id) AS sessions
       FROM ${TABLE}
       GROUP BY 1, 2, 3, 4, 5
       ORDER BY sessions DESC
       LIMIT 20"
fi
