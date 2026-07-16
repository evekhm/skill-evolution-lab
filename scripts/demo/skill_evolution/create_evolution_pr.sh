#!/usr/bin/env bash
# ============================================================================
# Create a PR with evolved skill for human review
# ============================================================================
#
# Creates a branch with ONLY the evolved SKILL.md, pushes it, and opens a PR.
# Uses agy (Antigravity CLI) to generate the PR description if available,
# otherwise falls back to a metrics table.
#
# Usage:
#   ./scripts/demo/skill_evolution/create_evolution_pr.sh --run-dir eval/runs/2026-05-18_...
#   ./scripts/demo/skill_evolution/create_evolution_pr.sh --run-dir eval/runs/... --version v2
#   ./scripts/demo/skill_evolution/create_evolution_pr.sh --run-dir eval/runs/... --dry-run
#   ./scripts/demo/skill_evolution/create_evolution_pr.sh --run-dir eval/runs/... --output /tmp/evolved.md
#   ./scripts/demo/skill_evolution/create_evolution_pr.sh --run-dir eval/runs/... --create-issue
#   ./scripts/demo/skill_evolution/create_evolution_pr.sh --run-dir eval/runs/... --issue 42
#   ./scripts/demo/skill_evolution/create_evolution_pr.sh --run-dir eval/runs/... \
#       --evolved-report eval/runs/.../v3_full_quality_report.json
#
# Quality metrics are auto-resolved from the run dir (vN_full_quality_report.json,
# vN_quality_report.json, best_vN_*, etc.). Use --evolved-report / --baseline-report
# to point at a specific report when the run dir uses a non-standard layout.
#
# Env vars (also settable in .env):
#   GITHUB_BASE_BRANCH - base branch for the PR (default: main)
#
# Requires: gh CLI authenticated, git
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$PROJECT_ROOT"

# Source .env if present
if [ -f "$PROJECT_ROOT/.env" ]; then
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.env"
fi

# Defaults
RUN_DIR=""
VERSION="v2"
AGENT="policy_agent"
DRY_RUN=false
OUTPUT_FILE=""
BASE_BRANCH="${GITHUB_BASE_BRANCH:-main}"
CREATE_ISSUE=false
ISSUE_NUMBER=""
EVOLVED_REPORT=""
BASELINE_REPORT_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --run-dir)          RUN_DIR="$2"; shift 2 ;;
        --version)          VERSION="$2"; shift 2 ;;
        --agent)            AGENT="$2"; shift 2 ;;
        --base-branch)      BASE_BRANCH="$2"; shift 2 ;;
        --output)           OUTPUT_FILE="$2"; shift 2 ;;
        --evolved-report)   EVOLVED_REPORT="$2"; shift 2 ;;
        --baseline-report)  BASELINE_REPORT_OVERRIDE="$2"; shift 2 ;;
        --dry-run)          DRY_RUN=true; shift ;;
        --create-issue)     CREATE_ISSUE=true; shift ;;
        --issue)            ISSUE_NUMBER="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,/^$/p' "$0" | grep '^#' | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$RUN_DIR" ]; then
    echo "ERROR: --run-dir is required" >&2
    exit 1
fi

# Resolve to absolute path before any branch switching
RUN_DIR="$(cd "$RUN_DIR" && pwd)"

# --- Resolve skill path from agent_registry.json ---
REGISTRY_FILE=""
for candidate in "eval/skill_evolution/agent_registry.json" "agent_registry.json"; do
    if [ -f "$PROJECT_ROOT/$candidate" ]; then
        REGISTRY_FILE="$PROJECT_ROOT/$candidate"
        break
    fi
done

if [ -n "$REGISTRY_FILE" ]; then
    SKILL_DIR=$(jq -r ".agents.\"${AGENT}\".skill_dir // empty" "$REGISTRY_FILE" 2>/dev/null)
    if [ -z "$SKILL_DIR" ]; then
        echo "ERROR: Agent '$AGENT' not found in $REGISTRY_FILE" >&2
        echo "Available: $(jq -r '.agents | keys | join(", ")' "$REGISTRY_FILE")" >&2
        exit 1
    fi
    SKILL_PATH="$SKILL_DIR/SKILL.md"
else
    echo "WARNING: No agent_registry.json found, using default path" >&2
    SKILL_PATH="agents/enterprise/${AGENT}/skill/SKILL.md"
fi

# --- Find evolved skill ---
EVOLVED_SKILL=""
for candidate in "${RUN_DIR}/best_${VERSION}_skill.md" \
                 "${RUN_DIR}/${VERSION}_${AGENT}_skill.md" \
                 "${RUN_DIR}/${VERSION}_skill.md"; do
    if [ -f "$candidate" ]; then
        EVOLVED_SKILL="$candidate"
        break
    fi
done

if [ -z "$EVOLVED_SKILL" ]; then
    echo "ERROR: No evolved skill found in $RUN_DIR for $VERSION" >&2
    exit 1
fi

# Resolve to absolute path before any branch switching
EVOLVED_SKILL="$(cd "$(dirname "$EVOLVED_SKILL")" && pwd)/$(basename "$EVOLVED_SKILL")"
EVOLVED_SIZE=$(wc -c < "$EVOLVED_SKILL")

# --- Extract metrics ---
# Rates in the quality reports are stored as percentages already (e.g. 78.9).
# Returns the value rounded to 1 decimal, or an empty string if unavailable.
extract_rate() {
    local report="$1" field="$2"
    if [ -n "$report" ] && [ -f "$report" ]; then
        jq -r ".summary.${field} // empty | . * 10 | round | . / 10 | tostring" \
            "$report" 2>/dev/null || true
    fi
}

# Resolve a quality report for a given version, trying the naming conventions
# produced by run_demo.sh (full-loop, --test-version, ablations) in priority order.
find_report() {
    local ver="$1" c
    for c in "${RUN_DIR}/${ver}_full_quality_report.json" \
             "${RUN_DIR}/${ver}_quality_report.json" \
             "${RUN_DIR}/best_${ver}_quality_report.json" \
             "${RUN_DIR}/${ver}_${AGENT}_quality_report.json"; do
        [ -f "$c" ] && { echo "$c"; return 0; }
    done
    # Glob fallback: vN_<anything>_quality_report.json
    c=$(ls "${RUN_DIR}/${ver}_"*_quality_report.json 2>/dev/null | sort | head -1 || true)
    [ -n "$c" ] && { echo "$c"; return 0; }
    return 1
}

# Signed delta between two rates (after - before), or "" if either is missing.
fmt_delta() {
    local before="$1" after="$2"
    if [ -z "$before" ] || [ -z "$after" ]; then return 0; fi
    awk "BEGIN{printf \"%+.1f\", $after - $before}"
}

# Render a rate as "NN.N%" or "n/a" — never a bare "?" or stray "%".
disp() { if [ -n "$1" ]; then echo "${1}%"; else echo "n/a"; fi; }

# Render a delta as "+N.Npp" / "-N.Npp", or em-dash when unavailable.
delta_disp() { if [ -n "$1" ]; then echo "${1}pp"; else echo "—"; fi; }

# --- Resolve reports (explicit override wins, else auto-resolve) ---
QUALITY_REPORT="${EVOLVED_REPORT:-$(find_report "$VERSION" || true)}"
if [ -n "$BASELINE_REPORT_OVERRIDE" ]; then
    BASELINE_REPORT="$BASELINE_REPORT_OVERRIDE"
else
    BASELINE_REPORT="$(find_report v0 || true)"
    [ -z "$BASELINE_REPORT" ] && \
        BASELINE_REPORT=$(ls "${RUN_DIR}/"*_quality_report.json 2>/dev/null | sort | head -1 || true)
fi
BASELINE_LABEL="baseline"
if [ -n "$BASELINE_REPORT" ]; then
    BASELINE_LABEL=$(basename "$BASELINE_REPORT" | sed 's/_quality_report\.json$//')
fi

EVOLVED_MEANINGFUL=$(extract_rate "$QUALITY_REPORT" "meaningful_rate")
EVOLVED_UNHELPFUL=$(extract_rate "$QUALITY_REPORT" "unhelpful_rate")
BASELINE_MEANINGFUL=$(extract_rate "$BASELINE_REPORT" "meaningful_rate")
BASELINE_UNHELPFUL=$(extract_rate "$BASELINE_REPORT" "unhelpful_rate")

MEANINGFUL_DELTA=$(fmt_delta "$BASELINE_MEANINGFUL" "$EVOLVED_MEANINGFUL")
UNHELPFUL_DELTA=$(fmt_delta "$BASELINE_UNHELPFUL" "$EVOLVED_UNHELPFUL")
M_DELTA_DISP=$(delta_disp "$MEANINGFUL_DELTA")
U_DELTA_DISP=$(delta_disp "$UNHELPFUL_DELTA")

BASE_M_DISP=$(disp "$BASELINE_MEANINGFUL")
EVO_M_DISP=$(disp "$EVOLVED_MEANINGFUL")
BASE_U_DISP=$(disp "$BASELINE_UNHELPFUL")
EVO_U_DISP=$(disp "$EVOLVED_UNHELPFUL")

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BRANCH="skill-evolution/${AGENT}-${VERSION}-${TIMESTAMP}"

# --- Honest, descriptive title (title and body share the same numbers) ---
# Show the version upgrade explicitly (vN-1 -> vN) and, when the evolved skill
# was scored, the meaningful-rate jump. Never emit a placeholder like "?%".
_vnum="${VERSION#v}"
if [[ "$_vnum" =~ ^[0-9]+$ ]] && [ "$_vnum" -gt 0 ]; then
    BASE_VERSION="v$((_vnum - 1))"
    UPGRADE="${BASE_VERSION} -> ${VERSION}"
else
    UPGRADE="${VERSION}"
fi
if [ -n "$EVOLVED_MEANINGFUL" ] && [ -n "$BASELINE_MEANINGFUL" ]; then
    TITLE="Evolve ${AGENT} skill ${UPGRADE}: meaningful ${BASE_M_DISP} -> ${EVO_M_DISP}${MEANINGFUL_DELTA:+ (${MEANINGFUL_DELTA}pp)}"
elif [ -n "$BASELINE_MEANINGFUL" ]; then
    TITLE="Evolve ${AGENT} skill ${UPGRADE}: baseline ${BASE_M_DISP} (evolved not yet scored)"
else
    TITLE="Evolve ${AGENT} skill ${UPGRADE} (pending eval)"
fi

if [ -z "$QUALITY_REPORT" ]; then
    echo "WARNING: no evolved quality report found in $RUN_DIR for ${VERSION}." >&2
    echo "         The PR will mark the evolved skill as 'not scored'." >&2
    echo "         Tip: run the test step (run_demo.sh --test-version ${VERSION#v})" >&2
    echo "         or pass --evolved-report <path> to include real metrics." >&2
fi

echo "Evolved skill:   $EVOLVED_SKILL (${EVOLVED_SIZE} chars)"
echo "Target:          $SKILL_PATH"
echo "Branch:          $BRANCH"
echo "Base branch:     $BASE_BRANCH"
echo "Baseline report: ${BASELINE_REPORT:-<none>}"
echo "Evolved report:  ${QUALITY_REPORT:-<none>}"
echo "Meaningful:      ${BASE_M_DISP} -> ${EVO_M_DISP}${MEANINGFUL_DELTA:+ (${MEANINGFUL_DELTA}pp)}"
echo "Unhelpful:       ${BASE_U_DISP} -> ${EVO_U_DISP}${UNHELPFUL_DELTA:+ (${UNHELPFUL_DELTA}pp)}"
echo ""

# --- Output-file mode ---
if [ -n "$OUTPUT_FILE" ]; then
    mkdir -p "$(dirname "$OUTPUT_FILE")"
    cp "$EVOLVED_SKILL" "$OUTPUT_FILE"
    echo "Written evolved skill to: $OUTPUT_FILE"
    exit 0
fi

# --- Create issue if requested ---
if $CREATE_ISSUE && [ -z "$ISSUE_NUMBER" ]; then
    ISSUE_TITLE="[Evolution] ${AGENT} skill ${VERSION} — meaningful ${BASE_M_DISP} → ${EVO_M_DISP}"
    ISSUE_BODY_PROMPT="Write a GitHub issue body for skill evolution of agent '${AGENT}' to version '${VERSION}'.
Use these metrics EXACTLY as given — do not invent, alter, or estimate any numbers:
Meaningful rate: ${BASE_M_DISP} -> ${EVO_M_DISP}${MEANINGFUL_DELTA:+ (${MEANINGFUL_DELTA}pp)}.
Unhelpful rate: ${BASE_U_DISP} -> ${EVO_U_DISP}${UNHELPFUL_DELTA:+ (${UNHELPFUL_DELTA}pp)}.
Skill size: ${EVOLVED_SIZE} chars. Run: $(basename "$RUN_DIR").
If a rate is 'n/a', state that it was not scored rather than guessing a value.
Include sections: Metadata table, Quality Impact, What Changed, Verification.
Output ONLY the issue body markdown."

    ISSUE_BODY=""
    if command -v agy &>/dev/null; then
        echo "Using agy to generate issue body..."
        ISSUE_BODY=$(agy -p "$ISSUE_BODY_PROMPT" 2>/dev/null) || true
    fi
    if [ -z "$ISSUE_BODY" ]; then
        ISSUE_BODY="## Metadata

| Field | Value |
|-------|-------|
| Agent | \`${AGENT}\` |
| Version | \`${VERSION}\` |
| Meaningful rate | ${BASE_M_DISP} → ${EVO_M_DISP}${MEANINGFUL_DELTA:+ (${MEANINGFUL_DELTA}pp)} |
| Unhelpful rate | ${BASE_U_DISP} → ${EVO_U_DISP}${UNHELPFUL_DELTA:+ (${UNHELPFUL_DELTA}pp)} |
| Skill size | ${EVOLVED_SIZE} chars |
| Run | \`$(basename "$RUN_DIR")\` |"
    fi

    if $DRY_RUN; then
        echo "[DRY RUN] Would create issue: $ISSUE_TITLE"
        echo ""
        echo "$ISSUE_BODY"
        echo ""
    else
        echo "Creating GitHub issue..."
        ISSUE_URL=$(gh issue create --title "$ISSUE_TITLE" --body "$ISSUE_BODY" 2>/dev/null) || true
        if [ -n "$ISSUE_URL" ]; then
            ISSUE_NUMBER=$(echo "$ISSUE_URL" | grep -oE '[0-9]+$')
            echo "Created issue #${ISSUE_NUMBER}: $ISSUE_URL"
        else
            echo "WARNING: Failed to create issue, continuing without it" >&2
        fi
    fi
fi

# --- Dry-run mode ---
if $DRY_RUN; then
    echo "[DRY RUN] Would create branch '$BRANCH', commit only '$SKILL_PATH', and open PR."
    [ -n "$ISSUE_NUMBER" ] && echo "[DRY RUN] PR would include: Fixes #$ISSUE_NUMBER"
    echo ""
    echo "Title: $TITLE"
    echo ""
    echo "Diff preview:"
    diff -u "$SKILL_PATH" "$EVOLVED_SKILL" | head -50 || true
    exit 0
fi

# --- Copy evolved skill to temp before branch switch ---
TMPFILE=$(mktemp /tmp/evolved_skill_XXXXXX.md)
cp "$EVOLVED_SKILL" "$TMPFILE"

# --- Stash uncommitted changes ---
STASHED=false
if ! git diff --quiet || ! git diff --cached --quiet; then
    git stash push -m "create_evolution_pr: temp stash"
    STASHED=true
fi

ORIGINAL_BRANCH=$(git rev-parse --abbrev-ref HEAD)

cleanup() {
    git checkout "$ORIGINAL_BRANCH" 2>/dev/null || true
    if $STASHED; then
        git stash pop 2>/dev/null || true
    fi
    rm -f "$TMPFILE"
}
trap cleanup EXIT

# --- Create branch from base, commit ONLY the skill file ---
git fetch origin "$BASE_BRANCH" --quiet
git checkout -b "$BRANCH" "origin/$BASE_BRANCH"

mkdir -p "$(dirname "$SKILL_PATH")"
cp "$TMPFILE" "$SKILL_PATH"
git add "$SKILL_PATH"
git commit -m "$(cat <<EOF
Evolve ${AGENT} skill to ${VERSION}

Meaningful rate: ${BASE_M_DISP} -> ${EVO_M_DISP}${MEANINGFUL_DELTA:+ (${MEANINGFUL_DELTA}pp)}
Unhelpful rate: ${BASE_U_DISP} -> ${EVO_U_DISP}${UNHELPFUL_DELTA:+ (${UNHELPFUL_DELTA}pp)}
Run: $(basename "$RUN_DIR")
EOF
)"

# --- Push ---
git push -u origin "$BRANCH"

# --- Generate PR body (try agy, fall back to static) ---
DIFF_TEXT=$(git diff "origin/${BASE_BRANCH}...HEAD" -- "$SKILL_PATH")

# Shared metrics table — the single source of truth for title and body numbers.
METRICS_TABLE="| Metric | Baseline (${BASELINE_LABEL}) | Evolved (${VERSION}) | Change |
|--------|:------------:|:-------------------:|:------:|
| Meaningful rate | ${BASE_M_DISP} | ${EVO_M_DISP} | ${M_DELTA_DISP} |
| Unhelpful rate | ${BASE_U_DISP} | ${EVO_U_DISP} | ${U_DELTA_DISP} |
| Skill size | — | ${EVOLVED_SIZE} chars | |"

PR_BODY=""
if command -v agy &>/dev/null; then
    echo "Using agy to generate PR description..."
    PR_BODY=$(agy -p "Write a pull request description for the following skill evolution change.
Agent: ${AGENT}, version: ${VERSION}

Use this exact quality metrics table verbatim (do not invent, alter, or estimate any numbers; 'n/a' means not scored):
${METRICS_TABLE}

Skill size: ${EVOLVED_SIZE} chars, run: $(basename "$RUN_DIR")

Diff:
${DIFF_TEXT:0:3000}

Output ONLY the PR body in markdown. Start with the metrics table above, then a summary of what changed in the skill. No preamble." 2>/dev/null) || true
fi

if [ -z "$PR_BODY" ]; then
    PR_BODY="## Skill Evolution: ${AGENT} ${VERSION}

${METRICS_TABLE}

Run: \`$(basename "$RUN_DIR")\`"
fi

# Append issue link if we have one
if [ -n "$ISSUE_NUMBER" ]; then
    PR_BODY="${PR_BODY}

Fixes #${ISSUE_NUMBER}"
fi

# --- Create PR via gh ---
PR_URL=$(gh pr create \
    --base "$BASE_BRANCH" \
    --head "$BRANCH" \
    --title "$TITLE" \
    --body "$PR_BODY")

echo ""
echo "PR created: $PR_URL"
