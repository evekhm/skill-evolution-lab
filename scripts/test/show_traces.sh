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
# No filters set -> label distribution of ALL traffic.
# Any filter set -> preview EXACTLY what the evolution pre-flight would
# fetch with that selector (same variables the evolution job reads):
#
#   EVAL_TIME_PERIOD          window, e.g. 6h / 24h / 7d   (default 6h)
#   AGENT_VERSION             skill version filter          (default: any)
#   QUALITY_APP_NAME          root agent app                (default knowledge_supervisor)
#   EVOLUTION_TRACE_LABELS    k=v,k2=v2 label filter        (default: none)
#
# Examples:
#   bash scripts/test/show_traces.sh                    # everything, grouped
#   EVOLUTION_TRACE_LABELS=$DEMO_LABEL bash scripts/test/show_traces.sh
#   EVAL_TIME_PERIOD=24h AGENT_VERSION=0 bash scripts/test/show_traces.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
set -a
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/.env"
set +a

TABLE="\`${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}\`"
MODE="${1:-summary}"
echo "TARGET: BigQuery ${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}"

# A filter in the environment means the caller wants the selector
# preview; the --selector flag is kept for backward compatibility.
if [ "${MODE}" = "--selector" ] || [ -n "${EVOLUTION_TRACE_LABELS:-}" ] \
    || [ -n "${AGENT_VERSION:-}" ] || [ -n "${EVAL_TIME_PERIOD:-}" ]; then
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
    # Label filters (k=v,k2=v2): a labeled session matches either via its
    # trace custom_tags (local runner) or via the run_labels side table
    # (deployed traffic — the generator records session->label rows there).
    SIDE_TABLE="\`${PROJECT_ID}.${DATASET_ID}.run_labels\`"
    HAS_SIDE=false
    bq show "${PROJECT_ID}:${DATASET_ID}.run_labels" >/dev/null 2>&1 && HAS_SIDE=true
    TRACE_LBL=""
    SIDE_HAVING="1=1"
    IFS=',' read -ra PAIRS <<< "${EVOLUTION_TRACE_LABELS:-}"
    for pair in "${PAIRS[@]:-}"; do
        [ -z "${pair}" ] && continue
        key="${pair%%=*}"; val="${pair#*=}"
        TRACE_LBL="${TRACE_LBL} AND JSON_VALUE(attributes, '\$.custom_tags.${key}') = '${val}'"
        SIDE_HAVING="${SIDE_HAVING} AND COUNTIF(label_key = '${key}' AND label_value = '${val}') > 0"
    done
    if [ -n "${TRACE_LBL}" ]; then
        LBL_SEL="SELECT DISTINCT session_id FROM ${TABLE} WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), ${INTERVAL}) ${TRACE_LBL}"
        if $HAS_SIDE; then
            LBL_SEL="${LBL_SEL} UNION DISTINCT SELECT session_id FROM ${SIDE_TABLE} WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), ${INTERVAL}) GROUP BY session_id HAVING ${SIDE_HAVING}"
        fi
        WHERE="${WHERE} AND session_id IN (${LBL_SEL})"
    fi

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
