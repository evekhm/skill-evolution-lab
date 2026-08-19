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
#   nudge     <repo> <pr_number> <nudge_json>       ({"sha": <head oid>})
#   relabel   <repo> <number>    -                  (re-derive labels from
#                                                    the existing ledger; the
#                                                    sweep's self-heal pass)
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

find_ledger_comment() { # -> base64 row or empty; rc 1 on FETCH failure
    # ARGUS_LOGIN (optional env, set by the workflows): restrict the
    # match to Argus-authored comments. Without it, any commenter on a
    # public repo could pre-plant a forged ledger comment that the
    # hourly relabel pass would then read unattended (R3-3). REST
    # appends "[bot]" to GitHub App logins, so both forms match.
    # Capture-then-parse (R6-2): a fetch error must fail loudly, never
    # read as "no ledger yet" — that misread would make mode_review
    # POST a second ledger comment and fork the recorded state. Full
    # capture also keeps head -1 from breaking gh's pagination pipe
    # (the R3-1 SIGPIPE class).
    local raw hit
    if ! raw=$(gh api --paginate "repos/${REPO}/issues/${NUMBER}/comments" 2>/dev/null); then
        echo "ERROR: comment fetch failed — cannot determine ledger state" >&2
        return 1
    fi
    hit=$(printf '%s' "$raw" | jq -r --arg who "${ARGUS_LOGIN:-}" '.[]
            | select(($who == "") or (.user.login == $who) or (.user.login == $who + "[bot]"))
            | select(.body | startswith("<!-- argus-ledger -->")) | [.id, .body] | @base64' \
        | head -1)
    # Misconfiguration guard (R5-2): a ledger that exists under a
    # DIFFERENT author than the filter expects means ARGUS_LOGIN is
    # wrong (or the app was renamed). Treating that as "no ledger"
    # would post a duplicate ledger comment and fork recorded state.
    if [ -z "$hit" ] && [ -n "${ARGUS_LOGIN:-}" ]; then
        if printf '%s' "$raw" | jq -e '.[]
              | select(.body | startswith("<!-- argus-ledger -->"))' >/dev/null 2>&1; then
            echo "ERROR: a ledger comment exists but none matches ARGUS_LOGIN='${ARGUS_LOGIN}' — refusing to create a duplicate; check the variable" >&2
            return 1
        fi
    fi
    printf '%s' "$hit"
}

extract_ledger_data() { # stdin: comment body -> data json (or {}); rc 1 on corrupt
    # Two distinct empty-looking cases (R2-2, then AEL#22 R3-3):
    # - NO data block at all -> the default shape (a fresh ledger).
    # - a PRESENT but unparseable block -> FAIL. Falling back to the
    #   default there would let a corrupted (or marker-injected) block
    #   silently erase recorded findings, and the hourly relabel would
    #   then flip labels to consensus:agreed off the empty state.
    #   Failing is loud: review/consensus turn the job red; the sweep's
    #   per-item guard skips just that item.
    local region out
    region=$(sed -n '/<!-- argus-ledger-data/,/^-->$/p' | sed '1d;$d')
    if [ -z "$region" ]; then
        echo '{"findings":[],"atlas_seen":false}'
        return 0
    fi
    if ! out=$(printf '%s\n' "$region" | jq -c '.' 2>/dev/null) || [ -z "$out" ]; then
        echo "ERROR: ledger data block present but unparseable — refusing to treat it as empty" >&2
        return 1
    fi
    echo "$out"
}

load_ledger() { # -> ledger data json (default shape when no ledger exists yet)
    local row
    row=$(find_ledger_comment)
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
        # The close-out digest (#111): written by the consensus path once
        # every finding is agreed/escalated, so the owner reads state from
        # this one comment instead of the whole thread.
        if [ "$(echo "$data" | jq -r '.consensus_summary // ""')" != "" ]; then
            echo "**Consensus summary**"
            echo ""
            echo "$data" | jq -r '.consensus_summary'
            echo ""
        fi
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
    row=$(find_ledger_comment)
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
    local data="$1" open secbug disputed pending seen
    open=$(echo "$data"    | jq '[.findings[] | select(.status=="open")] | length')
    # Consensus scope = security/bug rows at any NON-TERMINAL status
    # (R1-1, R4-1, then AEL#22 R7-1): a fixed row still needs the
    # peer's verdict — "fixed by Argus's word alone" must not shortcut
    # to consensus:agreed — while a WITHDRAWN row is a conceded false
    # positive whose stale atlas value ("dispute" from the exchange
    # that refuted it, or "pending") would otherwise pin the item at
    # consensus:disputed forever.
    secbug=$(echo "$data"  | jq '[.findings[] | select(.status!="withdrawn" and .severity!="suggestion")] | length')
    disputed=$(echo "$data" | jq '[.findings[] | select(.status!="withdrawn" and .severity!="suggestion" and .atlas=="dispute")] | length')
    pending=$(echo "$data" | jq '[.findings[] | select(.status!="withdrawn" and .severity!="suggestion" and .atlas=="pending")] | length')
    seen=$(echo "$data"    | jq -r '.atlas_seen')

    if [ "$open" -gt 0 ]; then
        set_label_pair "argus:findings" "argus:clean"
    else
        set_label_pair "argus:clean" "argus:findings"
    fi
    if [ "$disputed" -gt 0 ]; then
        set_label_pair "consensus:disputed" "consensus:pending" "consensus:agreed"
    elif [ "$secbug" -eq 0 ]; then
        # Never had anything in consensus scope (clean or
        # suggestion-only): agreed WITHOUT requiring atlas_seen. Atlas
        # legitimately posts no @argus-tagged verdict here, so
        # atlas_seen never flips and the old gate deadlocked such items
        # at consensus:pending forever (#109; PR #104 merged in that
        # state).
        set_label_pair "consensus:agreed" "consensus:pending" "consensus:disputed"
    elif [ "$pending" -gt 0 ] || [ "$seen" != "true" ]; then
        set_label_pair "consensus:pending" "consensus:agreed" "consensus:disputed"
    else
        set_label_pair "consensus:agreed" "consensus:pending" "consensus:disputed"
    fi
    echo "labels: open=${open} secbug=${secbug} disputed=${disputed} pending=${pending} atlas_seen=${seen}"
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
    # New security/bug rows get pending_since (UTC) — the dead-peer nudge
    # clock (#113 AT-1 exchange): Reviewed-head marker age resets on every
    # push, so "how long has Atlas owed a verdict" must live on the row.
    local data short now
    data=$(load_ledger)
    short="${HEAD_SHA:0:7}"
    now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    data=$(jq -c --slurpfile new "$INPUT" --arg short "$short" --arg now "$now" '
        .findings as $old
        | ($old | map(.id)) as $ids
        | .findings += [$new[0].findings[] | select(.id as $i | $ids | index($i) | not) |
            {id: (.id | gsub("\r|\n|\\|"; " ") | gsub("-->|<!--"; "→")),
             severity,
             title: (.title | gsub("\r|\n|\\|"; " ") | gsub("-->|<!--"; "→")),
             status: "open",
             atlas: (if .severity == "suggestion" then "—" else "pending" end),
             fixed_in: null, outcome: null}
            + (if .severity != "suggestion" then {pending_since: $now} else {} end)]
        | ($new[0].resolved) as $res
        | .findings |= map(if (.id as $i | $res | index($i)) and .status == "open"
              then .status = "fixed" | .fixed_in = $short else . end)
        | (if (($new[0].findings | length) + ($new[0].resolved | length)) > 0
           then del(.consensus_summary) else . end)' <<<"$data")
        # ^ a review round that CHANGES state (new findings or newly
        #   resolved rows) supersedes the close-out digest (AEL#22
        #   R1-4); a clean no-change round keeps it — deleting it there
        #   would orphan the digest forever, since a clean round gives
        #   Atlas nothing to verdict and the consensus path that
        #   rebuilds it never runs (R4-4).
    upsert_ledger "$data"
    apply_labels_from "$data"
}

# ---- mode: consensus ---------------------------------------------------

mode_consensus() {
    # Optional fields (both backward compatible with older consensus JSON):
    #   summary       — close-out digest rendered atop the ledger (#111)
    #   source        — "argus" on new_findings rows that are Argus's own
    #                   issue findings (R<issue>-N) being recorded at
    #                   reconciliation time (#110); argus_verdict then
    #                   carries the exchange outcome, same state machine.
    # Malformed OPTIONAL fields are dropped per-row before validation
    # instead of discarding the whole verdict payload (R4-3) — one bad
    # status string must not throw away every other recorded verdict.
    # Required-field failures still hard-fail below.
    local norm
    norm=$(mktemp)
    if jq '.updates |= map(
            (if has("status") and (.status != "withdrawn")
             then del(.status) else . end)
          | (if has("outcome") and
               ((.outcome | IN("agreed","conceded-by-argus","conceded-by-atlas","escalated")) | not)
             then del(.outcome) else . end))' "$INPUT" > "$norm" 2>/dev/null; then
        # Canonicalize both sides before comparing (AEL#22 R6-4):
        # comparing jq's formatted output against the raw input fires
        # the notice on every well-formed payload.
        if ! cmp -s <(jq -cS . "$norm" 2>/dev/null) <(jq -cS . "$INPUT" 2>/dev/null); then
            echo "consensus: dropped malformed optional status/outcome field(s)" >&2
        fi
        INPUT="$norm"
    fi
    if ! jq -e '
        (.updates | type == "array") and (.new_findings | type == "array") and
        (.escalated | type == "array") and
        (((.summary // "") | type == "string")) and
        (.updates | all((.id|type=="string") and (.atlas|IN("agree","dispute")) and
            ((has("status") | not) or (.status == "withdrawn")) and
            ((has("outcome") | not) or
             (.outcome | IN("agreed","conceded-by-argus","conceded-by-atlas","escalated"))))) and
        (.new_findings | all((.id|type=="string") and
            (.severity|IN("security","bug","suggestion")) and
            (.title|type=="string") and
            ((.source // "atlas") | IN("argus","atlas")) and
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
                    + (if $m.atlas == "agree" and ($f.status == "open" or $f.status == "fixed")
                       then {outcome: "agreed"} else {} end)
                    + (if ($m | has("status")) then {status: $m.status} else {} end)
                    + (if ($m | has("outcome")) then {outcome: $m.outcome} else {} end)
              end)
        | (.findings | map(.id)) as $ids
        | .findings += [$c[0].new_findings[] | select(.id as $i | $ids | index($i) | not) |
            {id: (.id | gsub("\r|\n|\\|"; " ") | gsub("-->|<!--"; "→")),
             severity,
             title: (.title | gsub("\r|\n|\\|"; " ") | gsub("-->|<!--"; "→")),
             status: "open",
             fixed_in: null, outcome: null}
            + (if .source then {source} else {} end)
            + (if .argus_verdict == "dispute"
               then {atlas: "dispute"}              # the open disagreement
               else {atlas: "agree", outcome: "agreed"} end)]
        | ($c[0].escalated) as $esc
        | .findings |= map(if (.id as $i | $esc | index($i))
              then .outcome = "escalated" else . end)
        | ([.findings[] | select(.status != "withdrawn"
              and .severity != "suggestion"
              and (.outcome // "") != "escalated"
              and (.atlas == "pending" or .atlas == "dispute"))]
           | length) as $unsettled
        | (if $unsettled > 0 then del(.consensus_summary) else . end)
        | (if (($c[0].summary // "") != "") and $unsettled == 0
           then .consensus_summary = ($c[0].summary | gsub("-->|<!--"; "→"))
           else . end)' <<<"$data")
        # ^ one invariant governs the digest (R6-3, then AEL#22 R4-2):
        #   it exists exactly while the post-merge state carries no
        #   pending or disputed security/bug verdict. Unsettled rows
        #   delete a stale digest and block a new one, whatever the
        #   incoming payload claims.

    upsert_ledger "$data"
    apply_labels_from "$data"
}

# ---- mode: nudge -------------------------------------------------------

# Dead-peer alert (#113): the sweep detected open security/bug findings
# whose Atlas verdict has been pending >24h at the PR's CURRENT head.
# One comment per head oid; the "Consensus-nudge:" marker is the dedupe
# token the sweep checks before nominating again.
mode_nudge() {
    local sha
    sha=$(jq -r '.sha // empty' "$INPUT")
    case "$sha" in (*[!0-9a-f]*|'') echo "ERROR: bad sha '${sha}'" >&2; exit 1;; esac
    # Exactly the full 40-char oid: the dedupe greps for the literal
    # "Consensus-nudge: <sha>", so a short nomination one hour and a
    # full one the next would slip past it (AEL#22 R1-2).
    if [ "${#sha}" -ne 40 ]; then
        echo "ERROR: sha must be the full 40-char head oid" >&2; exit 1
    fi
    # Dedupe in code, not in the sweep agent's judgement (R1-3): one
    # nudge per head oid, ever, regardless of what the agent nominates.
    # Fetch-then-grep, never gh|grep -q: under pipefail, grep -q's
    # early exit breaks gh's pipe mid-pagination and the dedupe check
    # reads as "not found" (R3-1). On fetch failure, fail CLOSED — a
    # dedupe we cannot verify must not post.
    local bodies
    if ! bodies=$(gh api --paginate "repos/${REPO}/issues/${NUMBER}/comments" \
        --jq '.[].body' 2>/dev/null); then
        echo "nudge: comment fetch failed — skipping (dedupe unverifiable)"
        return 0
    fi
    if grep -qF "Consensus-nudge: ${sha}" <<<"$bodies"; then
        echo "nudge: marker for ${sha:0:7} already present — skipping"
        return 0
    fi
    api POST "issues/${NUMBER}/comments" -f body="### Argus

Consensus check: this item has open security/bug findings awaiting the peer reviewer (Atlas) for more than 24 hours. @evekhm — the Atlas poller may be down.

— Argus · Claude on Vertex AI

Consensus-nudge: ${sha}" >/dev/null
    echo "nudge posted (head ${sha:0:7})"
}

# ---- mode: relabel -----------------------------------------------------

# Self-heal (#109): re-derive labels from the ledger already on the item.
# No comments, no ledger edits — with the secbug gate above this converges
# stuck consensus:pending labels (including on closed/merged items) and is
# a no-op when labels are already true. Run hourly by the sweep.
mode_relabel() {
    local row data
    row=$(find_ledger_comment)
    if [ -z "$row" ]; then
        echo "relabel: no ledger on #${NUMBER} — nothing to do"
        return 0
    fi
    data=$(echo "$row" | base64 -d | jq -r '.[1]' | extract_ledger_data)
    apply_labels_from "$data"
}

# Label definitions are only ensured by the modes that record new
# state. relabel runs hourly against up to 20 items and nudge posts a
# comment only — unconditional ensure_labels would burn 5 label POSTs
# per item per sweep for labels that necessarily exist once a ledger
# does (PR #114 AT-2).
case "$MODE" in
    review|consensus) ensure_labels ;;
esac
case "$MODE" in
    review)    mode_review ;;
    consensus) mode_consensus ;;
    nudge)     mode_nudge ;;
    relabel)   mode_relabel ;;
    *) echo "unknown mode: $MODE" >&2; exit 1 ;;
esac
