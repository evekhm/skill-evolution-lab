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

# ============================================================================
# Skill Evolution Demo
# ============================================================================
#
# End-to-end demonstration of automatic skill evolution from execution
# trajectories. Uses the ADK-based Skill Evolution Agent for all
# orchestration decisions (threshold gating, bottleneck detection,
# candidate selection, round control).
#
# The demo pipeline:
#   1. V0 baseline: a minimal human-written skill
#   2. Generate traffic and score quality -> see V0 failures
#   3. Evolve the skill via parallel analyst fleet + consolidation
#   4. Re-test with evolved skill -> see improvement
#   5. Optional: second evolution round (if enough failures remain)
#
# ============================================================================
# SCENARIOS
# ============================================================================
#
# 1) QUICK START — use pre-built V0 baseline (no traffic generation)
#
#    Runs the full evolution pipeline but skips V0 traffic generation and
#    scoring by reusing the reference baseline data at:
#      eval/skill_evolution/reference_runs/v0_baseline_demo/
#    This is the fastest way to demo evolution (~10 min for --quick).
#
#    Examples:
#      run_demo.sh --quick --reuse-v0
#      run_demo.sh --full --reuse-v0
#
# 2) FROM SCRATCH — generate V0 traffic, score, then evolve
#
#    Runs the entire pipeline end-to-end: restore V0 skill, generate traffic
#    from the baseline question set (demo_conversations.json for --full,
#    demo_quick.json for --quick), score it, then evolve.
#    Output goes to a new timestamped directory under eval/runs/.
#    Use --resume <dir> to write outputs to a specific directory instead.
#
#    Examples:
#      run_demo.sh --full                          # new timestamped dir
#      run_demo.sh --quick                         # smaller question set
#      run_demo.sh --full --resume eval/runs/my_run # explicit output dir
#
# 3) RESUME — reuse V0 data from a previous run, continue evolution
#
#    Picks up V0 traffic and scoring from an existing run directory and
#    feeds them into the evolution pipeline. Avoids re-generating traffic
#    and re-scoring when only the evolution logic changed.
#
#    a) Resume in-place (read + write to the same directory):
#         run_demo.sh --full --reuse-v0 --resume eval/runs/2026-05-28_1200_demo_full
#
#    b) Resume but redirect output to a new directory:
#         run_demo.sh --full --reuse-v0 eval/runs/2026-05-28_1200_demo_full
#       This copies V0 data from the old run into a fresh timestamped dir.
#
#    c) Resume from a bare traffic file (no quality report — will score fresh):
#         run_demo.sh --full --reuse-v0 path/to/v0_traffic.json
#
# 4) RESUME + RESCORE — reuse V0 traffic but force fresh scoring
#
#    Same as scenario 3 but re-runs the scorer even if a quality report
#    already exists. Useful when the scoring logic or golden evals changed.
#
#    a) Rescore in-place:
#         run_demo.sh --full --reuse-v0 --rescore --resume eval/runs/2026-05-28_1200_demo_full
#
#    b) Rescore into a new directory:
#         run_demo.sh --full --reuse-v0 eval/runs/2026-05-28_1200_demo_full --rescore
#
# 5) V0-ONLY — generate traffic and score, no evolution
#
#    Restores V0 skills, generates traffic, scores it, then stops.
#    Useful for testing persona changes, skill weakening, or establishing
#    a fresh baseline without running evolution.
#
#    Examples:
#      run_demo.sh --v0-only                       # default persona (alex)
#      run_demo.sh --v0-only --persona morgan       # morgan persona
#      run_demo.sh --v0-only --quick                # smaller question set
#
# 6) EVOLVE ONLY — skip traffic/scoring, run evolution on existing V0 data
#
#    Requires --resume pointing to a directory that already contains
#    v0_quality_report.json. Runs the evolution agent directly.
#
#    Examples:
#      run_demo.sh --evolve-only --resume eval/runs/2026-05-29_143341_demo_full
#      run_demo.sh --evolve-only --resume eval/runs/my_run --candidates 5
#      run_demo.sh --evolve-only --resume eval/runs/my_run --quick
#
# 7) TEST A SPECIFIC VERSION — deploy, traffic, score, restore
#
#    Deploys v<N> skills from an existing run directory, generates traffic,
#    scores it, then restores V0. Requires the run dir to contain
#    v<N>_policy_agent_skill.md and v<N>_supervisor_skill.md.
#
#    Examples:
#      run_demo.sh --test-version 1 --resume eval/runs/my_run
#      run_demo.sh --test-version 2 --resume eval/runs/my_run --quick
#
# ============================================================================
# FLAGS
# ============================================================================
#
#   --quick              22 questions (2 per category), ~15 min total
#   --full               55 questions (all categories) + held-out test split (default)
#   --reuse-v0 [path]    Reuse V0 data. Path is optional and can be:
#                          - a directory (copies traffic + scoring if available)
#                          - a .json file (traffic only, will score fresh)
#                          - omitted: uses reference baseline, or --resume dir
#   --rescore            Force re-scoring even when a quality report exists.
#                        Combine with --reuse-v0 to reuse traffic but re-score.
#   --resume <dir>       Write outputs to this directory instead of creating
#                        a new timestamped one. Also used as V0 data source
#                        when --reuse-v0 is given without a path.
#   --v0-only            Generate V0 traffic + score only, skip evolution.
#   --evolve-only        Skip traffic/scoring, run evolution on existing data.
#                        Requires --resume <dir> with v0_quality_report.json.
#   --rescore-only       Re-score existing v0/v1 traffic (no traffic regen),
#                        applying golden evals + agent scope context.
#                        Requires --resume <dir> with traffic JSONs.
#   --test-version <N>   Deploy v<N> skills from --resume dir, test, restore V0.
#   --persona <name>     User simulator persona: alex (default) or morgan.
#   --rounds <N>         Override number of evolution rounds (default: agent-decided).
#   --candidates <N>     Override number of candidates per round.
#   --min-failures <N>   Override minimum failure threshold for evolution.
#
# ============================================================================
# PREREQUISITES
# ============================================================================
#
#   - .env configured with PROJECT_ID
#   - GCP auth (gcloud auth application-default login)
#   - uv installed (Python package manager)
#
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Load environment
source "$PROJECT_ROOT/.env" 2>/dev/null || true

export PYTHONPATH="$PROJECT_ROOT"
export PYTHONWARNINGS="ignore"
export PYTHONUNBUFFERED=1
export LOGLEVEL="${LOGLEVEL:-WARNING}"
export AGENT_REGISTRY="${AGENT_REGISTRY:-$PROJECT_ROOT/eval/skill_evolution/agent_registry.json}"

# Paths
EVAL_DIR="$PROJECT_ROOT/eval"
POLICY_SKILL="$PROJECT_ROOT/agents/enterprise/policy_agent/skill"
BENEFITS_SKILL="$PROJECT_ROOT/agents/enterprise/benefits_agent/skill"
SUPERVISOR_SKILL="$PROJECT_ROOT/agents/enterprise/knowledge_supervisor/app/skill"

ORIGINAL_ARGS="$*"

# Defaults
MODE="full"
ROUNDS=""
CANDIDATES=""
REUSE_V0=false
REUSE_V0_PATH=""
RESCORE=false
MIN_FAILURES=""
V0_ONLY=false
EVOLVE_ONLY=false
RESCORE_ONLY=false
TEST_VERSION=""
PERSONA=""
QUESTIONS_OVERRIDE=""
# Turns per simulated conversation. Multi-turn (4) lets a follow-up recover a
# half-answered compound question, which masks the supervisor's decompose skill;
# --max-turns 1 measures the single-shot skill directly.
MAX_TURNS=4
# Held-out evolve/test split (Trace2Skill §2.1). On by default for --full:
# evolve on D_evolve (60%), report V0/V1 on the disjoint D_test (40%).
HELDOUT=true
HELDOUT_FRAC=0.6
# Model used for ALL local agents during traffic generation (EVAL_MODEL_ID).
# flash-lite is a weaker instruction-follower, which creates skill-fixable
# headroom for evolution. Same model is used for V0 and V1 (clean attribution).
EVAL_MODEL="${EVAL_MODEL_ID:-gemini-2.5-flash-lite}"

# V0 reference data (default for --reuse-v0 when no path given)
V0_REFERENCE_DIR="$PROJECT_ROOT/eval/skill_evolution/reference_runs/v0_baseline_demo"
V0_REFERENCE_TRAFFIC="$V0_REFERENCE_DIR/v0_traffic.json"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --quick)        MODE="quick"; shift ;;
        --full)         MODE="full"; shift ;;
        --rounds)       ROUNDS="$2"; shift 2 ;;
        --candidates)   CANDIDATES="$2"; shift 2 ;;
        --min-failures) MIN_FAILURES="$2"; shift 2 ;;
        --reuse-v0)
            REUSE_V0=true; shift
            # Optional: next arg is a path to dir or v0_traffic.json (not a flag)
            if [[ $# -gt 0 && "$1" != --* ]]; then
                REUSE_V0_PATH="$1"; shift
            fi
            ;;
        --rescore)      RESCORE=true; shift ;;
        --resume)       RUN_DIR="$2"; shift 2 ;;
        --v0-only)      V0_ONLY=true; shift ;;
        --eval-only)    V0_ONLY=true; shift ;;
        --evolve-only)  EVOLVE_ONLY=true; shift ;;
        --rescore-only) RESCORE_ONLY=true; shift ;;
        --test-version) TEST_VERSION="$2"; shift 2 ;;
        --max-turns)    MAX_TURNS="$2"; shift 2 ;;
        --persona)      PERSONA="$2"; shift 2 ;;
        --questions)    QUESTIONS_OVERRIDE="$2"; shift 2 ;;
        --model)        EVAL_MODEL="$2"; shift 2 ;;
        --no-heldout)   HELDOUT=false; shift ;;
        --heldout-frac) HELDOUT_FRAC="$2"; shift 2 ;;
        *)              echo "Unknown flag: $1"; exit 1 ;;
    esac
done

# All local agents (supervisor + sub-agents) run on this model during traffic
# generation and candidate scoring. Same model for V0 and V1 keeps the V0->V1
# delta attributable to the skill change, not the model.
export EVAL_MODEL_ID="$EVAL_MODEL"
# Gemini-3.x preview models are served from the Vertex GLOBAL endpoint; 2.5 from
# a region. Route automatically so --model gemini-3-* works out of the box.
case "$EVAL_MODEL" in
    gemini-3*) export GOOGLE_CLOUD_LOCATION=global REGION=global SUPERVISOR_REGION=global GOOGLE_GENAI_USE_VERTEXAI=True ;;
esac

# Initialize run directory
if [[ -z "${RUN_DIR:-}" ]]; then
    RUN_DIR="$EVAL_DIR/runs/$(date +%Y-%m-%d_%H%M%S)_demo_${MODE}"
fi
mkdir -p "$RUN_DIR"
DEMO_START_TS=$(date +%s)

# Quick mode pins the fast profile unless the caller chose values:
# 1 round, 3 candidates. Agent-decided runs were choosing 5 candidates
# + a second round, doubling runtime for rounds that scored worse.
if [ "$MODE" = "quick" ]; then
    ROUNDS="${ROUNDS:-1}"
    CANDIDATES="${CANDIDATES:-2}"
    # One target agent: evolving all three (supervisor+policy+benefits)
    # triples candidate scoring for no demo gain — the supervisor stage
    # alone reaches the headline number. EVOLVE_TARGET overrides.
    EVOLVE_TARGET="${EVOLVE_TARGET:-supervisor}"
fi

# One auto-generated label for the WHOLE demo run, tied 1:1 to the run
# folder name. Every traffic invocation inside inherits it via
# TRACE_LABELS, so this run is its own BigQuery slice — guaranteed
# distinct from everything already in the table. Override the label
# with DEMO_TRACE_LABEL=k=v; user-set TRACE_LABELS are kept additively.
DEMO_TRACE_LABEL="${DEMO_TRACE_LABEL:-demo_run=$(basename "$RUN_DIR")}"
export TRACE_LABELS="${TRACE_LABELS:+$TRACE_LABELS,}$DEMO_TRACE_LABEL"

# Local demo is a SANDBOX: the evolution agent's registry/PR/issue tools
# are disabled (BQ trace logging stays on). The PR is produced as a
# local artifact instead. Override with EVOLUTION_PUBLISH=1.
export EVOLUTION_PUBLISH="${EVOLUTION_PUBLISH:-0}"

# Tee output to log file
RUN_LOG="$RUN_DIR/run.log"
echo "$ $0 $ORIGINAL_ARGS" > "$RUN_LOG"
echo "" >> "$RUN_LOG"
exec > >(tee >(sed 's/\x1b\[[0-9;]*m//g' >> "$RUN_LOG")) 2>&1

cd "$PROJECT_ROOT"

echo "  [config] EVAL_MODEL_ID=$EVAL_MODEL_ID (all local agents)"
echo "  [config] BigQuery slice label: $DEMO_TRACE_LABEL"
echo "  [config] Quality gate: QUALITY_THRESHOLD=${QUALITY_THRESHOLD:-0.95} (skip evolution if V0 already meets it)"
echo "  [config] Agents: LOCAL in-process — every traffic call runs with"
echo "           --local --local-agents; the deployed stack receives ZERO"
echo "           requests from this run"

# =====================================================================
# Helpers
# =====================================================================

# SDK-style stage output (examples/agent_improvement_cycle): each
# banner closes the previous stage with a green check + elapsed time,
# then opens the next as a bold headline between dim separators.
# run.log stays plain — the tee pipeline strips ANSI codes.
BOLD=$'\033[1m'; DIM=$'\033[2m'; CYAN=$'\033[36m'; GREEN=$'\033[32m'; RESET=$'\033[0m'
_STAGE_START=""
_STAGE_NAME=""
# Demo step markers — numbering and titles IDENTICAL to the README's
# "Run the Demo" Steps 1-7, so the console maps 1:1 to the docs.
# Each step closes with its elapsed time (SDK agent_improvement_cycle
# step_start/step_end logic).
_STEP_T0=""; _STEP_NO=""
step_close() {
    if [ -n "$_STEP_T0" ]; then
        local _sel=$(( $(date +%s) - _STEP_T0 ))
        echo ""
        echo -e "  ${GREEN}\xe2\x9c\x94 STEP ${_STEP_NO}/7 completed in ${_sel}s.${RESET}"
        _STEP_T0=""
    fi
}
step() {
    step_close
    banner "STEP $1/7 \xe2\x80\x94 $2"
    echo -e "  ${DIM}README: Run the Demo > Step $1${RESET}"
    [ -n "${3:-}" ] && echo -e "  ${DIM}Goal: $3${RESET}"
    echo ""
    # The step's completion line comes from step_close (with the real
    # elapsed time) — clear the stage timer so the next banner doesn't
    # ALSO close the step header as a 0s stage.
    _STAGE_START=""
    _STEP_T0=$(date +%s); _STEP_NO="$1"
}
banner() {
    if [ -n "$_STAGE_START" ]; then
        local _el=$(( $(date +%s) - _STAGE_START ))
        echo ""
        echo -e "  ${GREEN}\xe2\x9c\x94 ${_STAGE_NAME} \xe2\x80\x94 ${_el}s${RESET}"
    fi
    echo ""
    echo -e "${DIM}$(printf '\xe2\x94\x81%.0s' $(seq 1 70))${RESET}"
    echo ""
    echo -e "  ${BOLD}${CYAN}\xe2\x96\xb6 $1${RESET}"
    echo ""
    _STAGE_START=$(date +%s)
    _STAGE_NAME="$1"
}

restore_v0() {
    cp "$POLICY_SKILL/SKILL.v0.md" "$POLICY_SKILL/SKILL.md"
    cp "$BENEFITS_SKILL/SKILL.v0.md" "$BENEFITS_SKILL/SKILL.md"
    cp "$SUPERVISOR_SKILL/SKILL.v0.md" "$SUPERVISOR_SKILL/SKILL.md"
    echo "  [restore_v0] policy=$(wc -c < "$POLICY_SKILL/SKILL.md")B benefits=$(wc -c < "$BENEFITS_SKILL/SKILL.md")B supervisor=$(wc -c < "$SUPERVISOR_SKILL/SKILL.md")B"
    # Restore eval_cases.json to baseline (remove evolution-added cases)
    local EVAL_CASES="$EVAL_DIR/data/eval_cases.json"
    local EVAL_CASES_V0="$EVAL_DIR/data/eval_cases.v0.json"
    if [ -f "$EVAL_CASES_V0" ]; then
        cp "$EVAL_CASES_V0" "$EVAL_CASES"
    fi
}

# Generate traffic with the CURRENTLY deployed skills against a question file,
# then score it. Used for held-out test-set scoring of V0 and V1.
#   $1 = question file, $2 = output label (e.g. v0_test, v1_test)
score_testset() {
    local qfile="$1" label="$2"
    banner "Held-out scoring: $label"
    uv run python agents/workflow/traffic_generator/main.py \
        --local --local-agents --multi-turn \
        --from-file "$qfile" \
        --max-turns "$MAX_TURNS" --concurrency 5 \
        $PERSONA_FLAG \
        -o "$RUN_DIR/${label}_traffic.json"
    uv run python eval/scoring/score_conversations.py \
        -i "$RUN_DIR/${label}_traffic.json" \
        -o "$RUN_DIR/${label}_report.json" \
        --tag-turns --trajectory-samples all --concurrency 10 \
        --eval-spec "$EVAL_DIR/data/eval_spec.json" \
        --report
    echo "  $label report: $RUN_DIR/${label}_report.json"
}

# =====================================================================
# Run the Skill Evolution Agent (ADK)
# =====================================================================

# Build persona flag for traffic generator
PERSONA_FLAG=""
[ -n "$PERSONA" ] && PERSONA_FLAG="--persona $PERSONA"

# Resolve questions file
# --quick uses two_defect_quick.json (25 questions, 2 per category)
# --full uses two_defect_evolve.json (55 questions, all categories)
if [ -n "$QUESTIONS_OVERRIDE" ]; then
    QUESTIONS_FILE="$QUESTIONS_OVERRIDE"
elif [ "$MODE" = "quick" ]; then
    QUESTIONS_FILE="$EVAL_DIR/data/questions/two_defect_lite.json"
else
    QUESTIONS_FILE="$EVAL_DIR/data/questions/two_defect_evolve.json"
fi

# Make the evolution agent's candidate scoring (score_candidate) use the same
# question set as the run, so --quick stays quick instead of validating every
# candidate against the full 55-question set.
export EVAL_QUESTIONS_FILE="$QUESTIONS_FILE"

# =====================================================================
# V0-only mode: traffic + score, then stop
# =====================================================================

if $V0_ONLY; then
    banner "V0 TRAFFIC + SCORING (${PERSONA:-alex})"
    echo "  Run directory: $RUN_DIR"
    echo "  Mode:          $MODE"
    echo "  Persona:       ${PERSONA:-alex}"
    echo "  Questions:     $QUESTIONS_FILE"
    echo "  Started:       $(date)"
    echo ""

    # Restore V0 skills for ALL agents
    restore_v0
    cp "$POLICY_SKILL/SKILL.md" "$RUN_DIR/v0_policy_skill.md"
    cp "$BENEFITS_SKILL/SKILL.md" "$RUN_DIR/v0_benefits_skill.md"
    cp "$SUPERVISOR_SKILL/SKILL.md" "$RUN_DIR/v0_supervisor_skill.md"
    echo "  Restored V0 skills (policy_agent + benefits_agent + supervisor)"

    # Generate traffic
    banner "Step 1: Generate V0 traffic"
    TRAFFIC_START=$(date +%s)
    uv run python agents/workflow/traffic_generator/main.py \
        --local --local-agents --multi-turn \
        --from-file "$QUESTIONS_FILE" \
        --max-turns "$MAX_TURNS" --concurrency 5 \
        $PERSONA_FLAG \
        -o "$RUN_DIR/v0_traffic.json"
    TRAFFIC_END=$(date +%s)
    echo "  Traffic done in $((TRAFFIC_END - TRAFFIC_START))s"

    # Score (with golden Q&A ground truth)
    banner "Step 2: Score V0 traffic"
    SCORE_START=$(date +%s)
    uv run python eval/scoring/score_conversations.py \
        -i "$RUN_DIR/v0_traffic.json" \
        -o "$RUN_DIR/v0_quality_report.json" \
        --tag-turns --trajectory-samples all --concurrency 10 \
        --eval-spec "$EVAL_DIR/data/eval_spec.json" \
        --report
    SCORE_END=$(date +%s)
    echo "  Scoring done in $((SCORE_END - SCORE_START))s"

    # Print summary
    banner "V0 Quality Summary"
    uv run python -c "
import json, sys
with open('$RUN_DIR/v0_quality_report.json') as f:
    r = json.load(f)
s = r['summary']
print(f\"  Persona:       ${PERSONA:-alex}\")
print(f\"  Sessions:      {s['total_sessions']}\")
print(f\"  Meaningful:    {s['meaningful']} ({s['meaningful_rate']:.1f}%)\")
print(f\"  Unhelpful:     {s['unhelpful']} ({s['unhelpful_rate']:.1f}%)\")
print(f\"  Corrections:   {s.get('avg_corrections', 0):.1f} avg\")
print(f\"  Tool calls:    {s.get('avg_tool_calls', 0):.1f} avg\")
total = $((TRAFFIC_END - TRAFFIC_START)) + $((SCORE_END - SCORE_START))
print(f\"  Total time:    {total}s\")
"

    banner "Done (v0-only)"
    echo "  Traffic:  $RUN_DIR/v0_traffic.json"
    echo "  Report:   $RUN_DIR/v0_quality_report.json"
    echo "  Report:   $RUN_DIR/v0_quality_report.md"
    echo "  Skills:   $RUN_DIR/v0_policy_skill.md, v0_supervisor_skill.md"
    echo "  Finished: $(date)"
    exit 0
fi

# =====================================================================
# Evolve-only mode: skip traffic/scoring, run evolution directly
# =====================================================================

if $EVOLVE_ONLY; then
    QUALITY_REPORT="$RUN_DIR/v0_quality_report.json"
    if [[ ! -f "$QUALITY_REPORT" ]]; then
        echo "ERROR: $QUALITY_REPORT not found." >&2
        echo "  --evolve-only requires --resume <dir> with existing V0 data." >&2
        exit 1
    fi

    banner "EVOLVE ONLY"
    echo "  Run directory: $RUN_DIR"
    echo "  Quality report: $QUALITY_REPORT"
    echo "  Mode:          $MODE"
    echo "  Rounds:        ${ROUNDS:-agent-decided}"
    echo "  Candidates:    ${CANDIDATES:-agent-decided}"
    echo "  Min failures:  ${MIN_FAILURES:-agent-decided}"
    echo "  Started:       $(date)"
    echo ""

    # Restore V0 skills so evolution starts from baseline
    restore_v0

    AGENT_FLAGS="--report $QUALITY_REPORT --run-dir $RUN_DIR"
    if [ "$MODE" = "quick" ]; then
        AGENT_FLAGS="$AGENT_FLAGS --quick"
    fi
    [ -n "$ROUNDS" ] && AGENT_FLAGS="$AGENT_FLAGS --rounds $ROUNDS"
    [ -n "$CANDIDATES" ] && AGENT_FLAGS="$AGENT_FLAGS --candidates $CANDIDATES"
    [ -n "$MIN_FAILURES" ] && AGENT_FLAGS="$AGENT_FLAGS --min-failures $MIN_FAILURES"
    [ -n "${EVOLVE_TARGET:-}" ] && AGENT_FLAGS="$AGENT_FLAGS --mode $EVOLVE_TARGET"

    EVOLVE_START=$(date +%s)
    step_close
uv run python agents/workflow/skill_evolution_agent/main.py $AGENT_FLAGS 2>&1 | \
        tee "$RUN_DIR/agent_output.log"
    EVOLVE_END=$(date +%s)

    banner "Done (evolve-only)"
    echo "  All outputs: $RUN_DIR"
    echo "  Elapsed:     $((EVOLVE_END - EVOLVE_START))s"
    echo "  Finished:    $(date)"
echo "  Wall time:   $(( ($(date +%s) - DEMO_START_TS) / 60 ))m $(( ($(date +%s) - DEMO_START_TS) % 60 ))s"
    exit 0
fi

# =====================================================================
# Rescore-only mode: re-score existing traffic (no traffic regen)
# Scores existing v0_traffic.json and v1_full_traffic.json with the
# golden evals + agent scope context. Use after fixing scorer wiring or
# updating scope_decisions.
# =====================================================================

if $RESCORE_ONLY; then
    banner "RESCORE ONLY"
    echo "  Run directory:  $RUN_DIR"
    echo "  Golden evals:   $EVAL_DIR/data/golden_evals.json"
    echo "  Agent context:  $EVAL_DIR/data/agent_context.json"
    echo "  Started:        $(date)"

    rescore_one() {
        local traffic="$1" report="$2" label="$3"
        if [[ ! -f "$traffic" ]]; then
            echo "  SKIP $label: $traffic not found"
            return
        fi
        banner "Rescore $label"
        local t0 t1
        t0=$(date +%s)
        uv run python eval/scoring/score_conversations.py \
            -i "$traffic" \
            -o "$report" \
            --tag-turns --trajectory-samples all --concurrency 10 \
            --eval-spec "$EVAL_DIR/data/eval_spec.json" \
            --report
        t1=$(date +%s)
        echo "  $label rescored in $((t1 - t0))s -> $report"
    }

    rescore_one "$RUN_DIR/v0_traffic.json" \
        "$RUN_DIR/v0_quality_report.json" "V0"
    rescore_one "$RUN_DIR/v1_full_traffic.json" \
        "$RUN_DIR/v1_full_quality_report.json" "V1"

    banner "Done (rescore-only)"
    echo "  Finished: $(date)"
    exit 0
fi

# =====================================================================
# Test a specific skill version: deploy, traffic, score, restore
# =====================================================================

if [[ -n "$TEST_VERSION" ]]; then
    V="$TEST_VERSION"
    POLICY_SRC="$RUN_DIR/v${V}_policy_agent_skill.md"
    SUPER_SRC="$RUN_DIR/v${V}_supervisor_skill.md"

    # Validate skills exist in run dir
    if [[ ! -f "$POLICY_SRC" ]]; then
        echo "ERROR: $POLICY_SRC not found" >&2; exit 1
    fi
    if [[ ! -f "$SUPER_SRC" ]]; then
        echo "ERROR: $SUPER_SRC not found" >&2; exit 1
    fi

    banner "TEST V${V} SKILL (${PERSONA:-alex})"
    echo "  Run directory: $RUN_DIR"
    echo "  Mode:          $MODE"
    echo "  Persona:       ${PERSONA:-alex}"
    echo "  Questions:     $QUESTIONS_FILE"
    echo "  Policy skill:  $POLICY_SRC"
    echo "  Supervisor:    $SUPER_SRC"
    echo "  Started:       $(date)"
    echo ""

    # Deploy V<N> skills
    cp "$POLICY_SRC" "$POLICY_SKILL/SKILL.md"
    cp "$SUPER_SRC" "$SUPERVISOR_SKILL/SKILL.md"
    echo "  Deployed V${V} skills (policy_agent + supervisor)"

    # Tag agent version for BQ logging
    export AGENT_VERSION="v${V}"

    # Generate traffic
    banner "Step 1: Generate V${V} traffic"
    TRAFFIC_START=$(date +%s)
    uv run python agents/workflow/traffic_generator/main.py \
        --local --local-agents --multi-turn \
        --from-file "$QUESTIONS_FILE" \
        --max-turns "$MAX_TURNS" --concurrency 5 \
        $PERSONA_FLAG \
        -o "$RUN_DIR/v${V}_full_traffic.json"
    TRAFFIC_END=$(date +%s)
    echo "  Traffic done in $((TRAFFIC_END - TRAFFIC_START))s"

    # Score
    banner "Step 2: Score V${V} traffic"
    SCORE_START=$(date +%s)
    uv run python eval/scoring/score_conversations.py \
        -i "$RUN_DIR/v${V}_full_traffic.json" \
        -o "$RUN_DIR/v${V}_full_quality_report.json" \
        --tag-turns --trajectory-samples all --concurrency 10 \
        --eval-spec "$EVAL_DIR/data/eval_spec.json" \
        --report
    SCORE_END=$(date +%s)
    echo "  Scoring done in $((SCORE_END - SCORE_START))s"

    # Restore V0
    restore_v0
    echo "  Restored V0 skills"

    # Print summary
    banner "V${V} Quality Summary"
    uv run python -c "
import json
with open('$RUN_DIR/v${V}_full_quality_report.json') as f:
    r = json.load(f)
s = r['summary']
print(f'  Version:       v${V}')
print(f'  Persona:       ${PERSONA:-alex}')
print(f'  Sessions:      {s[\"total_sessions\"]}')
print(f'  Meaningful:    {s[\"meaningful\"]} ({s[\"meaningful_rate\"]:.1f}%)')
print(f'  Unhelpful:     {s[\"unhelpful\"]} ({s[\"unhelpful_rate\"]:.1f}%)')
print(f'  Corrections:   {s.get(\"avg_corrections\", 0):.1f} avg')
print(f'  Tool calls:    {s.get(\"avg_tool_calls\", 0):.1f} avg')
total = $((TRAFFIC_END - TRAFFIC_START)) + $((SCORE_END - SCORE_START))
print(f'  Total time:    {total}s')
gs = s.get('golden_eval_summary')
if gs:
    print()
    print(f'  Golden Q&A:    {gs[\"matched\"]}/{gs[\"total_sessions\"]} matched')
    print(f'    Matched meaningful:   {gs[\"matched_meaningful_rate\"]:.1f}%')
    print(f'    Unmatched meaningful: {gs[\"unmatched_meaningful_rate\"]:.1f}%')
    if gs['mismatches']:
        print(f'    Failed with ground truth: {len(gs[\"mismatches\"])}')
"

    banner "Done (test v${V})"
    echo "  Traffic:  $RUN_DIR/v${V}_full_traffic.json"
    echo "  Report:   $RUN_DIR/v${V}_full_quality_report.json"
    echo "  Report:   $RUN_DIR/v${V}_full_quality_report.md"
    echo "  Finished: $(date)"
    exit 0
fi

# =====================================================================
# Full evolution pipeline
# =====================================================================

# Held-out evolve/test split (Trace2Skill §2.1): patches + candidate scoring
# use D_evolve; V0/V1 are reported on the disjoint D_test. Full mode only.
TESTSET=""
if $HELDOUT && [ "$MODE" = "full" ] && ! $REUSE_V0; then
    banner "HELD-OUT SPLIT (evolve/test)"
    uv run python "$EVAL_DIR/data/questions/split_questions.py" "$QUESTIONS_FILE" \
        --evolve-frac "$HELDOUT_FRAC" \
        --out-evolve "$RUN_DIR/heldout.evolve.json" \
        --out-test "$RUN_DIR/heldout.test.json"
    export EVAL_QUESTIONS_FILE="$RUN_DIR/heldout.evolve.json"
    TESTSET="$RUN_DIR/heldout.test.json"
    echo "  Evolving on D_evolve; will report V0/V1 on D_test ($TESTSET)"
fi

banner "SKILL EVOLUTION AGENT (ADK)"
echo "  Run directory: $RUN_DIR"
echo "  Rounds:        ${ROUNDS:-agent-decided}"
echo "  Candidates:    ${CANDIDATES:-agent-decided}"
echo "  Min failures:  ${MIN_FAILURES:-agent-decided}"
echo "  Mode:          $MODE"
echo "  Persona:       ${PERSONA:-alex}"
echo "  Reuse V0:      $REUSE_V0"
echo "  Started:       $(date)"
echo ""

if $REUSE_V0; then
    # Resolve V0 source: explicit path > resume directory > default reference
    if [[ -n "$REUSE_V0_PATH" ]]; then
        V0_SRC="$REUSE_V0_PATH"
    elif [[ -f "$RUN_DIR/v0_traffic.json" ]]; then
        V0_SRC="$RUN_DIR"
    else
        V0_SRC="$V0_REFERENCE_DIR"
    fi

    if [[ -d "$V0_SRC" ]]; then
        V0_TRAFFIC_SRC="$V0_SRC/v0_traffic.json"
        V0_REPORT_SRC="$V0_SRC/v0_quality_report.json"
    elif [[ -f "$V0_SRC" ]]; then
        V0_TRAFFIC_SRC="$V0_SRC"
        V0_REPORT_SRC=""
    else
        echo "ERROR: V0 source not found: $V0_SRC" >&2
        exit 1
    fi

    if [[ ! -f "$V0_TRAFFIC_SRC" ]]; then
        echo "ERROR: V0 traffic not found: $V0_TRAFFIC_SRC" >&2
        exit 1
    fi

    echo "  Reusing V0 traffic: $V0_TRAFFIC_SRC"
    echo "  Reusing V0 traffic: $V0_TRAFFIC_SRC"
    # cp -n avoids "same file" error when V0_SRC == RUN_DIR (resume in-place)
    cp -n "$V0_TRAFFIC_SRC" "$RUN_DIR/v0_traffic.json" 2>/dev/null || true

    step 1 "Reset to the V0 baseline" "start from the known-weak V0 skill so the improvement is measurable"
    restore_v0
    cp -n "$POLICY_SKILL/SKILL.md" "$RUN_DIR/v0_policy_skill.md" 2>/dev/null || true
    cp -n "$BENEFITS_SKILL/SKILL.md" "$RUN_DIR/v0_benefits_skill.md" 2>/dev/null || true
    cp -n "$SUPERVISOR_SKILL/SKILL.md" "$RUN_DIR/v0_supervisor_skill.md" 2>/dev/null || true

    if [[ -n "${V0_REPORT_SRC:-}" && -f "${V0_REPORT_SRC:-}" ]] && ! $RESCORE; then
        # Report available and --rescore not set — reuse scoring
        echo "  Reusing V0 quality report: $V0_REPORT_SRC"
        cp -n "$V0_REPORT_SRC" "$RUN_DIR/v0_quality_report.json" 2>/dev/null || true
        # Copy or generate the Markdown report
        V0_MD_SRC="${V0_REPORT_SRC%.json}.md"
        if [[ -f "$V0_MD_SRC" ]]; then
            cp -n "$V0_MD_SRC" "$RUN_DIR/v0_quality_report.md" 2>/dev/null || true
        elif [[ ! -f "$RUN_DIR/v0_quality_report.md" ]]; then
            uv run python eval/scoring/score_conversations.py \
                --report-from-json "$RUN_DIR/v0_quality_report.json"
        fi
    else
        # No report — score fresh with current SDK scorer
        echo "  Scoring V0 traffic (fresh)..."
        SCORE_START=$(date +%s)
        uv run python eval/scoring/score_conversations.py \
            -i "$RUN_DIR/v0_traffic.json" \
            -o "$RUN_DIR/v0_quality_report.json" \
            --tag-turns --trajectory-samples all --concurrency 10 \
            --eval-spec "$EVAL_DIR/data/eval_spec.json" \
            --report
        SCORE_END=$(date +%s)
        echo "  V0 scoring done in $((SCORE_END - SCORE_START))s"
    fi

    AGENT_FLAGS="--report $RUN_DIR/v0_quality_report.json --run-dir $RUN_DIR"
    if [ "$MODE" = "quick" ]; then
        AGENT_FLAGS="$AGENT_FLAGS --quick"
    fi
else
    # Restore the V0 baseline skills BEFORE the full loop runs its pre-flight,
    # so the V0 measurement reflects the true weak baseline — not whatever a
    # previous run left deployed (which would have no evolution headroom).
    step 1 "Reset to the V0 baseline" "start from the known-weak V0 skill so the improvement is measurable"
    restore_v0
    cp "$POLICY_SKILL/SKILL.md" "$RUN_DIR/v0_policy_skill.md" 2>/dev/null || true
    cp "$BENEFITS_SKILL/SKILL.md" "$RUN_DIR/v0_benefits_skill.md" 2>/dev/null || true
    cp "$SUPERVISOR_SKILL/SKILL.md" "$RUN_DIR/v0_supervisor_skill.md" 2>/dev/null || true
    echo "  Restored V0 baseline skills (policy_agent + benefits_agent + supervisor)"
    AGENT_FLAGS="--full-loop --run-dir $RUN_DIR"
    if [ "$MODE" = "quick" ]; then
        AGENT_FLAGS="$AGENT_FLAGS --quick"
    fi
fi

# Optional overrides — only pass when explicitly set by the user
[ -n "$ROUNDS" ] && AGENT_FLAGS="$AGENT_FLAGS --rounds $ROUNDS"
[ -n "$CANDIDATES" ] && AGENT_FLAGS="$AGENT_FLAGS --candidates $CANDIDATES"
[ -n "$MIN_FAILURES" ] && AGENT_FLAGS="$AGENT_FLAGS --min-failures $MIN_FAILURES"
    [ -n "${EVOLVE_TARGET:-}" ] && AGENT_FLAGS="$AGENT_FLAGS --mode $EVOLVE_TARGET"

step_close
uv run python agents/workflow/skill_evolution_agent/main.py $AGENT_FLAGS 2>&1 | \
    tee "$RUN_DIR/agent_output.log" || \
    echo "  WARNING: agent step exited non-zero — continuing to restore/summary (see agent_output.log)"

# Held-out evaluation: the agent leaves V1 deployed. Score V1 on the disjoint
# test set, snapshot V1, restore V0, then score V0 on the same test set. These
# two reports are the headline, overfitting-free V0->V1 numbers.
if [ -n "$TESTSET" ]; then
    score_testset "$TESTSET" v1_test
    cp "$POLICY_SKILL/SKILL.md"     "$RUN_DIR/v1_policy_skill.md"
    cp "$BENEFITS_SKILL/SKILL.md"   "$RUN_DIR/v1_benefits_skill.md"
    cp "$SUPERVISOR_SKILL/SKILL.md" "$RUN_DIR/v1_supervisor_skill.md"
    restore_v0
    score_testset "$TESTSET" v0_test
    banner "HELD-OUT RESULT (disjoint D_test)"
    # Headline on the GROUND-TRUTH (golden-matched) rate, not the generic
    # usefulness judge -- the judge mislabels verbose, tool-grounded answers
    # (see the skill lab). Falls back silently if the field is absent.
    gt () { jq -r '.summary.golden_eval_summary.matched_meaningful_rate // "n/a"' "$1" 2>/dev/null; }
    echo "  V0 (test): $RUN_DIR/v0_test_report.json   ground-truth $(gt "$RUN_DIR/v0_test_report.json")%"
    echo "  V1 (test): $RUN_DIR/v1_test_report.json   ground-truth $(gt "$RUN_DIR/v1_test_report.json")%"
    echo "  V1 skills snapshotted: $RUN_DIR/v1_*_skill.md (V0 now restored)"

    # Triage: how many skill-fixable failures evolution auto-healed, plus the
    # owner-routed backlog of failures it CANNOT fix (tool bugs -> ENG, missing
    # facts -> KNOWLEDGE, out-of-scope -> PRODUCT).
    banner "TRIAGE (what evolution fixed vs what it can't)"
    uv run python eval/scoring/triage_report.py --run-dir "$RUN_DIR" \
        -o "$RUN_DIR/TRIAGE.md" || echo "  (triage step failed; see logs)"
fi

# --- PR as a local artifact: branch + commit + pr_preview.md, no push.
# Preview the version with the BEST measured rate (the agent can evolve
# past its own peak: a later round may score worse than an earlier one).
BEST_V=""; BEST_RATE=-1; BEST_REPORT=""
for f in "$RUN_DIR"/v[0-9]*_report.json "$RUN_DIR"/v[0-9]*_quality_report.json \
         "$RUN_DIR"/candidate_*_report.json; do
    [ -f "$f" ] || continue
    v=$(basename "$f" | grep -oE '^v[0-9]+' || true)
    [ "$v" = "v0" ] && continue
    rate=$(jq -r '.summary.meaningful_rate // -1' "$f" 2>/dev/null)
    if awk "BEGIN{exit !($rate > $BEST_RATE)}"; then
        BEST_RATE="$rate"; BEST_REPORT="$f"
        # candidate reports carry no version; the deployed winner is
        # the highest vN skill snapshot in the run dir
        if [ -z "$v" ]; then
            BEST_V=$(ls "$RUN_DIR" | grep -oE '^v[0-9]+' | grep -v '^v0$' | sort -V | tail -1)
        else
            BEST_V="$v"
        fi
    fi
done
if [ -n "$BEST_V" ]; then
    step 4 "Review the PR" "the learning as a reviewable artifact: metrics, diff, regression cases"
    banner "PR PREVIEW: $BEST_V at ${BEST_RATE}% (local branch + pr_preview.md, nothing pushed)"
    bash "$SCRIPT_DIR/create_evolution_pr.sh" \
        --run-dir "$RUN_DIR" --version "$BEST_V" --local \
        --agent "${EVOLVE_TARGET:-policy_agent}" \
        --evolved-report "$BEST_REPORT" \
        || echo "  (pr preview failed; see logs)"
fi

step_close
echo ""
echo -e "  ${DIM}STEPS 5-6/7 \xe2\x80\x94 Merge to activate + Verify the fix: deployed-path"
echo -e "  steps; in the sandbox the PR stays a local artifact (pr_preview.md)${RESET}"

step 7 "Roll back" "leave the system at V0; evolved skills stay snapshotted in the run dir"
if declare -f restore_v0 >/dev/null; then
    restore_v0 || echo "  (restore failed — check agents/enterprise/*/skill/)"
    echo "  Evolved skills remain in $RUN_DIR as vN_*_skill.md"
fi
step_close

# --- SUMMARY.md: one file that reads the whole run ---
{
    echo "# Demo Run Summary — $(basename "$RUN_DIR")"
    echo ""
    echo "- Wall time: $(( ($(date +%s) - DEMO_START_TS) / 60 ))m $(( ($(date +%s) - DEMO_START_TS) % 60 ))s"
    echo "- BigQuery slice: \`$DEMO_TRACE_LABEL\`"
    echo "  (\`EVOLUTION_TRACE_LABELS=$DEMO_TRACE_LABEL bash scripts/test/show_traces.sh\`)"
    echo "- Published anywhere: $([ "${EVOLUTION_PUBLISH}" = "0" ] && echo "NO (sandbox — registry/PR/issue disabled)" || echo "YES (EVOLUTION_PUBLISH=1)")"
    echo "- Agents: LOCAL in-process; zero requests to the deployed stack"
    echo "- Live skills: restored to V0; evolved versions snapshotted here as vN_*_skill.md"
    echo ""
    echo "## Quality (meaningful rate)"
    echo ""
    echo "| Version | Rate |"
    echo "|---|---|"
    v0r=$(jq -r '.summary.meaningful_rate // "?"' "$RUN_DIR/v0_quality_report.json" 2>/dev/null)
    echo "| V0 baseline | ${v0r}% |"
    for f in "$RUN_DIR"/v[0-9]*_report.json "$RUN_DIR"/v[0-9]*_quality_report.json \
             "$RUN_DIR"/candidate_*_report.json; do
        [ -f "$f" ] || continue
        n=$(basename "$f"); v=$(echo "$n" | grep -oE '^v[0-9]+' || echo "${n%_report.json}")
        [ "$v" = "v0" ] && continue
        echo "| $v | $(jq -r '.summary.meaningful_rate // "?"' "$f")% |"
    done
    [ -n "$BEST_V" ] && echo "" && echo "Winner previewed as PR: **$BEST_V (${BEST_RATE}%)** -> pr_preview.md"
    _thr=$(awk "BEGIN{printf \"%.0f\", ${QUALITY_THRESHOLD:-0.95}*100}")
    if [ -n "$BEST_V" ] && awk "BEGIN{exit !($BEST_RATE >= $_thr)}"; then
        echo "Quality gate: winner ${BEST_RATE}% MEETS the ${_thr}% threshold"
    elif [ -n "$BEST_V" ]; then
        echo "Quality gate: winner ${BEST_RATE}% below the ${_thr}% threshold — another cycle is warranted"
    fi
    echo ""
    echo "## Files worth reading"
    echo ""
    echo "- \`run.log\` — full console output of the run"
    echo "- \`v0_quality_report.json/.md\` — the judged baseline (failures = evolution input)"
    echo "- \`_score_candidate_N_report.json\` — each candidate's replay score"
    echo "- \`vN_*_skill.md\` — every evolved skill, per version"
    echo "- \`pr_preview.md\` — the PR as a local artifact (branch name inside)"
    echo "- \`TRIAGE.md\` — what evolution fixed vs what it cannot fix (if generated)"
} > "$RUN_DIR/SUMMARY.md"

banner "Done"
echo "  Summary:     $RUN_DIR/SUMMARY.md"
echo ""
echo "  To reset EVERYTHING before a fresh run (skill files + registry"
echo "  newest revision + live agents back to V0):"
echo "    bash scripts/demo/skill_evolution/rollback_demo.sh"
echo "  Optional — also delete this run's BigQuery slice:"
echo "    bash scripts/demo/skill_evolution/cleanup_label.sh $DEMO_TRACE_LABEL"
echo "  All outputs: $RUN_DIR"
echo "  This run's BigQuery slice:"
echo "    EVOLUTION_TRACE_LABELS=$DEMO_TRACE_LABEL bash scripts/test/show_traces.sh"
echo "  Finished:    $(date)"
echo "  Wall time:   $(( ($(date +%s) - DEMO_START_TS) / 60 ))m $(( ($(date +%s) - DEMO_START_TS) % 60 ))s"
echo ""
echo "  To publish the previewed PR:"
echo "    ./scripts/demo/skill_evolution/create_evolution_pr.sh --run-dir $RUN_DIR --version ${LATEST_V:-v1}"
