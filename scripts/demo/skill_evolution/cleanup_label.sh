#!/usr/bin/env bash
# Delete ONE labeled slice of traces so an experiment can restart clean.
#
# Scope-safe by construction: deletes only sessions matching the label
# (trace custom_tags OR the run_labels side table) plus their run_labels
# rows. The rest of the table is untouchable from here — there is no
# truncate path. The cheapest restart needs no deletion at all:
#   export DEMO_LABEL="experiment=round2"
#
# Usage:
#   cleanup_label.sh                     # uses $DEMO_LABEL
#   cleanup_label.sh experiment=round1
#   cleanup_label.sh experiment=round1 --yes   # skip confirmation
#
# Note: BigQuery cannot DELETE rows still in the streaming buffer
# (~last 30 min of agent writes). If that bites, the script says so —
# wait and re-run, or just switch to a fresh label.

set -euo pipefail
cd "$(dirname "$0")/../../.."
set -a
# shellcheck disable=SC1091
source .env
set +a

LABEL=""
YES=false
for arg in "$@"; do
    case "$arg" in
        --yes) YES=true ;;
        *)     LABEL="$arg" ;;
    esac
done
LABEL="${LABEL:-${DEMO_LABEL:-}}"

if [[ -z "$LABEL" || "$LABEL" != *=* ]]; then
    echo "ERROR: no label. Pass k=v (e.g. experiment=round1) or export DEMO_LABEL."
    exit 1
fi
KEY="${LABEL%%=*}"; VAL="${LABEL#*=}"

case "$KEY" in
    traffic_source|agent_version|sw_version|agent)
        echo "ERROR: refusing to delete by system tag '${KEY}' — it matches"
        echo "far more than one experiment. Use your own label key or run_id."
        exit 1 ;;
esac

EVENTS="\`${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}\`"
SIDE="\`${PROJECT_ID}.${DATASET_ID}.run_labels\`"

HAS_SIDE=false
bq show "${PROJECT_ID}:${DATASET_ID}.run_labels" >/dev/null 2>&1 && HAS_SIDE=true

SEL="SELECT DISTINCT session_id FROM ${EVENTS} WHERE JSON_VALUE(attributes, '\$.custom_tags.${KEY}') = '${VAL}'"
if $HAS_SIDE; then
    SEL="${SEL} UNION DISTINCT SELECT session_id FROM ${SIDE} WHERE label_key = '${KEY}' AND label_value = '${VAL}'"
fi

echo "TARGET: BigQuery ${PROJECT_ID}.${DATASET_ID}.${TABLE_ID}"
echo "=== Slice matching ${LABEL} ==="
bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false --format=pretty \
  "SELECT COUNT(*) AS events, COUNT(DISTINCT session_id) AS sessions
   FROM ${EVENTS} WHERE session_id IN (${SEL})"

if ! $YES; then
    read -r -p "Delete this slice (events + run_labels rows)? [y/N] " ans
    [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "Aborted."; exit 0; }
fi

if ! bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false \
    "DELETE FROM ${EVENTS} WHERE session_id IN (${SEL})"; then
    echo ""
    echo "DELETE failed — most likely rows from the last ~30 min are still"
    echo "in the streaming buffer. Wait and re-run, or restart with a fresh"
    echo "label instead: export DEMO_LABEL=\"${KEY}=<new-value>\""
    exit 1
fi

if $HAS_SIDE; then
    bq query --project_id="${PROJECT_ID}" --use_legacy_sql=false \
      "DELETE FROM ${SIDE} WHERE session_id IN (
         SELECT session_id FROM ${SIDE}
         WHERE label_key = '${KEY}' AND label_value = '${VAL}')"
fi

echo ""
echo "Slice '${LABEL}' deleted. Verify:"
echo "  EVOLUTION_TRACE_LABELS=${LABEL} bash scripts/test/show_traces.sh"
