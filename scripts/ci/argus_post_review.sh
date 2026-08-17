#!/usr/bin/env bash
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

# Argus trusted posting step. The review agent writes structured JSON;
# THIS script does every GitHub write. Authority is enforced here, in
# code, not in prompts: review events are hardcoded to COMMENT (never
# APPROVE / REQUEST_CHANGES), endpoints are fixed, and the
# Reviewed-head marker the sweep depends on is appended
# deterministically rather than trusted to the model.
#
# Modes:
#   review    <repo> <pr_number> <findings_json>  <head_sha>
#   consensus <repo> <number>    <consensus_json>
#
# Env: GH_TOKEN (reviewer app installation token), DRY_RUN=1 to print
# payloads instead of posting.
#
# Ledger: one issue comment holding the marker <!-- argus-ledger -->
# and machine state in an HTML comment:
#   <!-- argus-ledger-data
#   {json}
#   -->
# Consensus scope: security and bug findings require an Atlas verdict;
# suggestions are recorded but never block consensus:agreed.

set -euo pipefail

MODE="${1:?mode}"; REPO="${2:?repo}"; NUMBER="${3:?number}"; INPUT="${4:?json path}"
HEAD_SHA="${5:-}"
LEDGER_MARK='<!-- argus-ledger -->'
DRY_RUN="${DRY_RUN:-0}"

api() { # api <method> <path> [jq args...]
    local method="$1" path="$2"; shift 2
    if [ "$DRY_RUN" = "1" ] && [ "$method" != "GET" ]; then
        echo "[dry-run] $method $path $*" >&2
        cat /dev/null
        return 0
    fi
    gh api --method "$method" "repos/${REPO}/${path}" "$@"
}

ensure_labels() {
    local name color desc
    if [ "$DRY_RUN" = "1" ]; then echo "[dry-run] ensure labels" >&2; return; fi
    while IFS='|' read -r name color desc; do
        gh api --method POST "repos/${REPO}/labels" \
            -f name="$name" -f color="$color" -f description="$desc" \
            >/dev/null 2>&1 || true   # 422 = exists
    done <<'EOF'
argus:findings|d93f0b|Argus has open findings on this item
argus:clean|0e8a16|Argus reviewed and found nothing to flag
consensus:pending|fbca04|Awaiting peer (Atlas) verdicts on security/bug findings
consensus:agreed|0e8a16|Both reviewers agree on all security/bug findings
consensus:disputed|b60205|Active or escalated reviewer disagreement
EOF
}

# ---- ledger state ------------------------------------------------------

find_ledger_comment() { # -> "id<TAB>body" or empty
    gh api --paginate "repos/${REPO}/issues/${NUMBER}/comments" \
        --jq '.[] | select(.body | contains("<!-- argus-ledger -->")) | [.id, .body] | @base64' \
        | head -1
}

extract_ledger_data() { # stdin: comment body -> data json (or {})
    sed -n '/<!-- argus-ledger-data/,/^-->$/p' | sed '1d;$d' | jq -c '.' 2>/dev/null \
        || echo '{"findings":[],"atlas_seen":false}'
}

load_ledger() { # -> ledger data json (default shape when no ledger exists yet)
    local row
    row=$(find_ledger_comment || true)
    if [ -n "$row" ]; then
        echo "$row" | base64 -d | jq -r '.[1]' | extract_ledger_data
    else
        echo '{"findings":[],"atlas_seen":false}'
    fi
}

render_ledger() { # $1 data json -> markdown body
    local data="$1"
    {
        echo "$LEDGER_MARK"
        echo "### Argus findings ledger"
        echo ""
        echo "_Maintained by Argus (Claude on Vertex AI); the Atlas column is Atlas's independent verdict (Gemini)._"
        echo ""
        echo "Consensus scope: security and bug findings need both reviewers'"
        echo "agreement; suggestions are recorded but never block it."
        echo ""
        echo "| ID | Sev | Finding | Status | Atlas | Fixed in | Outcome |"
        echo "|---|---|---|---|---|---|---|"
        echo "$data" | jq -r '.findings[] | "| \(.id) | \(.severity) | \(.title) | \(.status) | \(.atlas) | \(.fixed_in // "—") | \(.outcome // "—") |"'
        echo ""
        echo "<!-- argus-ledger-data"
        echo "$data" | jq '.'
        echo "-->"
    }
}

upsert_ledger() { # $1 data json
    local data="$1" body row
    body=$(render_ledger "$data")
    row=$(find_ledger_comment || true)
    if [ -n "$row" ]; then
        local id
        id=$(echo "$row" | base64 -d | jq -r '.[0]')
        api PATCH "issues/comments/${id}" -f body="$body" >/dev/null
        echo "ledger: updated comment ${id}"
    else
        api POST "issues/${NUMBER}/comments" -f body="$body" >/dev/null
        echo "ledger: created"
    fi
}

# ---- labels ------------------------------------------------------------

set_label_pair() { # $1 add $2... remove
    local add="$1"; shift
    api POST "issues/${NUMBER}/labels" -f "labels[]=${add}" >/dev/null
    local rm
    for rm in "$@"; do
        api DELETE "issues/${NUMBER}/labels/$(printf '%s' "$rm" | jq -sRr @uri)" \
            >/dev/null 2>&1 || true
    done
}

apply_labels_from() { # $1 data json
    local data="$1" open disputed pending seen
    open=$(echo "$data"    | jq '[.findings[] | select(.status=="open")] | length')
    disputed=$(echo "$data" | jq '[.findings[] | select(.status=="open" and .severity!="suggestion" and .atlas=="dispute")] | length')
    pending=$(echo "$data" | jq '[.findings[] | select(.status=="open" and .severity!="suggestion" and .atlas=="pending")] | length')
    seen=$(echo "$data"    | jq -r '.atlas_seen')

    if [ "$open" -gt 0 ]; then
        set_label_pair "argus:findings" "argus:clean"
    else
        set_label_pair "argus:clean" "argus:findings"
    fi
    if [ "$disputed" -gt 0 ]; then
        set_label_pair "consensus:disputed" "consensus:pending" "consensus:agreed"
    elif [ "$pending" -gt 0 ] || [ "$seen" != "true" ]; then
        set_label_pair "consensus:pending" "consensus:agreed" "consensus:disputed"
    else
        set_label_pair "consensus:agreed" "consensus:pending" "consensus:disputed"
    fi
    echo "labels: open=${open} disputed=${disputed} pending=${pending} atlas_seen=${seen}"
}

# ---- review body -------------------------------------------------------

# Build the PR-review markdown from findings.json. $1 "true" folds every
# finding into the body with a file:line suffix (used by the inline-anchor
# retry); "false" lists only non-inline findings and leaves the inline
# ones for inline review comments. The header, the model-family trailer,
# and the "Reviewed-head:" marker (the sweep's completion signal) are
# appended here in code, never trusted to the model.
review_body() { # $1 fold(true|false)  $2 verdict_line -> body on stdout
    jq -r --arg v "$2" --arg sha "$HEAD_SHA" --argjson fold "$1" '
        def fmt:
            if $fold
            then "\n**[\(.id)] \(.title)** (\(.severity)\(if .file then ", \(.file):\(.line // "?")" else "" end))\n\n\(.body)"
            else "\n**[\(.id)] \(.title)** (\(.severity))\n\n\(.body)"
            end;
        "### Argus review\n\n" + $v + "\n\n" + .summary + "\n" +
        ([.findings[] | select($fold or (.inline != true)) | fmt] | join("\n")) +
        "\n\n— Argus · Claude on Vertex AI" +
        "\n\nReviewed-head: " + $sha' "$INPUT"
}

# ---- mode: review ------------------------------------------------------

mode_review() {
    [ -n "$HEAD_SHA" ] || { echo "review mode needs head_sha"; exit 1; }

    # Validate the agent's output. On failure: plain fallback comment
    # (marker included, so the sweep never re-loops the PR) and a red
    # job so the failure is noticed.
    if ! jq -e '
        (.schema == 1) and (.verdict | IN("clean","findings")) and
        (.summary | type == "string") and
        (.findings | type == "array" and length <= 30) and
        (.findings | all((.id|type=="string") and
            (.severity|IN("security","bug","suggestion")) and
            (.title|type=="string") and (.body|type=="string"))) and
        (.resolved | type == "array")' "$INPUT" >/dev/null 2>&1; then
        api POST "issues/${NUMBER}/comments" -f body="### Argus review

The review ran but its structured output failed validation — see the workflow run log for the raw findings.

— Argus · Claude on Vertex AI

Reviewed-head: ${HEAD_SHA}" >/dev/null
        echo "ERROR: findings.json failed validation" >&2
        exit 1
    fi

    local n_sec n_bug n_sug n_res verdict_line body payload
    n_sec=$(jq '[.findings[] | select(.severity=="security")] | length' "$INPUT")
    n_bug=$(jq '[.findings[] | select(.severity=="bug")] | length' "$INPUT")
    n_sug=$(jq '[.findings[] | select(.severity=="suggestion")] | length' "$INPUT")
    n_res=$(jq '.resolved | length' "$INPUT")
    if [ "$((n_sec + n_bug + n_sug))" -eq 0 ]; then
        verdict_line="Argus verdict: clean"
    else
        verdict_line="Argus verdict: $((n_sec + n_bug + n_sug)) finding(s) (${n_sec} security, ${n_bug} bug, ${n_sug} suggestion)"
    fi
    [ "$n_res" -gt 0 ] && verdict_line="${verdict_line} · resolved this round: ${n_res}"

    body=$(review_body false "$verdict_line")

    payload=$(jq -c --arg body "$body" --arg sha "$HEAD_SHA" '
        {commit_id: $sha, event: "COMMENT", body: $body,
         comments: [.findings[] | select(.inline == true) |
            {path: .file, line: .line, side: "RIGHT",
             body: "**[\(.id)] \(.title)** (\(.severity))\n\n\(.body)"}]}' "$INPUT")

    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] POST pulls/${NUMBER}/reviews:"; echo "$payload" | jq .
    elif ! echo "$payload" | gh api --method POST "repos/${REPO}/pulls/${NUMBER}/reviews" --input - >/dev/null; then
        # Inline anchors can 422 when a line is not in the diff — retry
        # with every finding folded into the body instead of dropping it.
        echo "inline review rejected — retrying with body-only findings" >&2
        body=$(review_body true "$verdict_line")
        jq -cn --arg body "$body" --arg sha "$HEAD_SHA" \
            '{commit_id: $sha, event: "COMMENT", body: $body}' \
            | gh api --method POST "repos/${REPO}/pulls/${NUMBER}/reviews" --input - >/dev/null
    fi
    echo "review posted (${n_sec}s/${n_bug}b/${n_sug}sg, resolved ${n_res})"

    # Merge into ledger: new rows for new findings; resolved -> fixed.
    local data short
    data=$(load_ledger)
    short="${HEAD_SHA:0:7}"
    data=$(jq -c --slurpfile new "$INPUT" --arg short "$short" '
        .findings as $old
        | ($old | map(.id)) as $ids
        | .findings += [$new[0].findings[] | select(.id as $i | $ids | index($i) | not) |
            {id: (.id | gsub("\r|\n|\\|"; " ") | gsub("-->"; "→")),
             severity,
             title: (.title | gsub("\r|\n|\\|"; " ") | gsub("-->"; "→")),
             status: "open",
             atlas: (if .severity == "suggestion" then "—" else "pending" end),
             fixed_in: null, outcome: null}]
        | ($new[0].resolved) as $res
        | .findings |= map(if (.id as $i | $res | index($i)) and .status == "open"
              then .status = "fixed" | .fixed_in = $short else . end)' <<<"$data")
    upsert_ledger "$data"
    apply_labels_from "$data"
}

# ---- mode: consensus ---------------------------------------------------

mode_consensus() {
    if ! jq -e '
        (.updates | type == "array") and (.new_findings | type == "array") and
        (.escalated | type == "array") and
        (.updates | all((.id|type=="string") and (.atlas|IN("agree","dispute")))) and
        (.new_findings | all((.id|type=="string") and
            (.severity|IN("security","bug","suggestion")) and
            (.title|type=="string") and
            (.argus_verdict|IN("agree","dispute"))))' \
        "$INPUT" >/dev/null 2>&1; then
        echo "ERROR: consensus.json failed validation" >&2
        exit 1
    fi

    local data
    data=$(load_ledger)

    data=$(jq -c --slurpfile c "$INPUT" '
        .atlas_seen = true
        | ($c[0].updates) as $u
        | .findings |= map(. as $f |
            (($u | map(select(.id == $f.id)) | first) // null) as $m
            | if $m == null then $f else
                $f + {atlas: $m.atlas}
                    + (if $m.atlas == "agree" and $f.status == "open"
                       then {outcome: "agreed"} else {} end)
                    + (if ($m | has("status")) then {status: $m.status} else {} end)
                    + (if ($m | has("outcome")) then {outcome: $m.outcome} else {} end)
              end)
        | (.findings | map(.id)) as $ids
        | .findings += [$c[0].new_findings[] | select(.id as $i | $ids | index($i) | not) |
            {id: (.id | gsub("\r|\n|\\|"; " ") | gsub("-->"; "→")),
             severity,
             title: (.title | gsub("\r|\n|\\|"; " ") | gsub("-->"; "→")),
             status: "open",
             fixed_in: null, outcome: null}
            + (if .argus_verdict == "dispute"
               then {atlas: "dispute"}              # the open disagreement
               else {atlas: "agree", outcome: "agreed"} end)]
        | ($c[0].escalated) as $esc
        | .findings |= map(if (.id as $i | $esc | index($i))
              then .outcome = "escalated" else . end)' <<<"$data")

    upsert_ledger "$data"
    apply_labels_from "$data"
}

ensure_labels
case "$MODE" in
    review)    mode_review ;;
    consensus) mode_consensus ;;
    *) echo "unknown mode: $MODE" >&2; exit 1 ;;
esac
