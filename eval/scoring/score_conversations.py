#!/usr/bin/env python3
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

"""Score traffic generator conversations — thin shim delegating to the SDK.

All evaluation logic (metrics, classification, scoring, report formatting)
lives in the SDK's ``quality_report.py``.  This file only provides:

  1. SDK discovery via ``ensure_sdk``.
  2. A Python API (``generate_quality_report``) for programmatic callers.
  3. A CLI that accepts ``-i``/``-o`` flags and delegates to the SDK.

Scope grounding and golden-Q&A matching  live
in the SDK; pass an eval spec via ``--eval-spec`` (or auto-discovered
``eval/data/eval_spec.json``).

Usage:
    python eval/scoring/score_conversations.py \\
        --input eval/runs/.../traffic.json \\
        --output eval/runs/.../quality_report.json \\
        --eval-spec eval/data/eval_spec.json \\
        --report
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

import google.auth
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)

env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path, override=False)

_, project_id = google.auth.default()
PROJECT_ID = os.getenv("PROJECT_ID", project_id)
REGION = os.getenv("REGION", "us-central1")

os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = (
    os.getenv("MODEL_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "global"
)  # model endpoint, not infra region: gemini-3.x is global-only
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

# ---------------------------------------------------------------------------
# SDK — single source of truth for all evaluation logic
# ---------------------------------------------------------------------------
from ensure_sdk import import_sdk_module  # noqa: E402

_sdk = None


def _get_sdk():
    """Load the SDK quality_report module on first use.

    Lazy so this module stays importable (and its pure helpers testable)
    in environments with no SDK checkout configured.
    """
    global _sdk
    if _sdk is None:
        _sdk = import_sdk_module("quality_report")
    return _sdk


class NothingScoreableError(ValueError):
    """Every record in the input was error-shaped (infrastructure failures)."""


def exclude_error_shaped(
    conversations: list[dict],
) -> tuple[list[dict], list[str], list[str]]:
    """Preflight: keep infrastructure failures away from the judge.

    The traffic generator writes ``ERROR: {e}`` into the transcript and
    sets ``errors`` on the record when a send fails, and the record still
    lands in the results file. A judge scores those strings as unhelpful
    without complaint, which has produced fake 0% rates before
    (Verification Contract, "error-shaped answers").

    A record is *excluded* when nothing scoreable can be salvaged: the
    final response is empty or ``ERROR:``-shaped, the ``errors`` flag is
    set with no error turn in the transcript to cut at (the generator
    always writes one, so a flag-only record is corrupt), or no completed
    exchange precedes the first error turn. A multi-turn record that
    failed part-way but holds completed exchanges is *kept*: a copy is
    scored with the transcript truncated at the first error turn —
    trailing unanswered user turns dropped; ``user_turns``, the final
    response, and the tag-derived ``corrections``/``verifications``
    counters recomputed from the kept turns; ``preflight_truncated``
    set — so late-turn quota failures neither bias the sample toward
    short conversations nor read as the agent ignoring the last question.

    Returns ``(scoreable, excluded_ids, truncated_ids)``.
    """
    scoreable, excluded, truncated = [], [], []
    for c in conversations:
        final = str(c.get("response") or c.get("final_response") or "")
        turns = [t for t in (c.get("conversation") or []) if isinstance(t, dict)]
        first_error = next(
            (i for i, t in enumerate(turns)
             if t.get("role") != "user"
             and str(t.get("text") or "").startswith("ERROR:")),
            None,
        )
        error_shaped = (bool(c.get("errors")) or final.startswith("ERROR:")
                        or first_error is not None)
        if not error_shaped:
            scoreable.append(c)
            continue
        session_id = str(c.get("session_id") or c.get("id") or "?")
        if not final or final.startswith("ERROR:") or first_error is None:
            excluded.append(session_id)
            continue
        kept_turns = turns[:first_error]
        # The generator appends the user turn before the send that failed,
        # so the cut transcript ends on an unanswered question — drop it,
        # or the judge scores the infra failure as the agent ignoring it.
        while kept_turns and kept_turns[-1].get("role") == "user":
            kept_turns.pop()
        agent_texts = [
            str(t.get("text") or "") for t in kept_turns
            if t.get("role") != "user" and str(t.get("text") or "").strip()
        ]
        if not agent_texts:
            excluded.append(session_id)
            continue
        copy = {**c, "conversation": kept_turns, "errors": 0,
                "preflight_truncated": True}
        if "user_turns" in copy:
            copy["user_turns"] = sum(
                1 for t in kept_turns if t.get("role") == "user")
        # The generator increments these per user-turn tag before the send
        # that failed — recount them over the kept turns or the report
        # claims a correction the judge never saw.
        for field, tag in (("corrections", "CORRECTION"),
                           ("verifications", "VERIFY")):
            if field in copy:
                copy[field] = sum(
                    1 for t in kept_turns
                    if t.get("role") == "user" and t.get("tag") == tag)
        for key in ("response", "final_response"):
            if key in copy:
                copy[key] = agent_texts[-1]
        scoreable.append(copy)
        truncated.append(session_id)
    return scoreable, excluded, truncated


def compare_reports(report_files: list[str]) -> None:
    """Compare multiple quality reports side by side.

    Args:
        report_files: List of "path:label" or plain path strings.
    """
    reports = []
    for spec in report_files:
        if ":" in spec:
            path, label = spec.rsplit(":", 1)
        else:
            path = spec
            label = os.path.basename(path).replace("_quality_report.json", "")
        with open(path) as f:
            data = json.load(f)
        reports.append((label, data))

    labels = [r[0] for r in reports]
    print(f"\n{'Metric':<25}", end="")
    for label in labels:
        print(f"  {label:>12}", end="")
    print()
    print("-" * (25 + 14 * len(labels)))

    for field in ("meaningful_rate", "unhelpful_rate", "correction_rate"):
        print(f"{field.replace('_', ' ').title():<25}", end="")
        for _, r in reports:
            print(f"  {r['summary'][field]:>11.1f}%", end="")
        print()

    # Denominators can differ when the preflight excluded error-shaped
    # records; a side-by-side rate comparison must say so.
    print(f"{'Total Sessions':<25}", end="")
    for _, r in reports:
        print(f"  {r['summary'].get('total_sessions', '?'):>12}", end="")
    print()
    print(f"{'Excluded (infra)':<25}", end="")
    for _, r in reports:
        n = (r["summary"].get("excluded_error_shaped") or {}).get("count", 0)
        print(f"  {n:>12}", end="")
    print()

    dims = ["correctness", "tool_usage", "specificity",
            "scope_compliance", "first_time_right"]
    print()
    for dim in dims:
        print(f"  {dim:<23}", end="")
        for _, r in reports:
            val = r["summary"]["dimension_averages"].get(dim, 0)
            print(f"  {val:>12.2f}", end="")
        print()

    all_cats: set[str] = set()
    for _, r in reports:
        for s in r.get("sessions", []):
            all_cats.add(s.get("category", "unknown"))

    print(f"\n{'Category':<25}", end="")
    for label in labels:
        print(f"  {label:>12}", end="")
    print()
    print("-" * (25 + 14 * len(labels)))

    for cat in sorted(all_cats):
        print(f"  {cat:<23}", end="")
        for _, r in reports:
            cat_sessions = [
                s for s in r.get("sessions", [])
                if s.get("category") == cat
            ]
            if cat_sessions:
                meaningful = sum(
                    1 for s in cat_sessions
                    if s["metrics"]["response_usefulness"]["category"]
                    in ("meaningful", "declined")
                )
                rate = meaningful / len(cat_sessions) * 100
                print(f"  {rate:>11.1f}%", end="")
            else:
                print(f"  {'N/A':>12}", end="")
        print()
    print()


# ---------------------------------------------------------------------------
# Public API for programmatic callers
# ---------------------------------------------------------------------------


def generate_quality_report(
    conversations: list[dict],
    eval_spec: dict | None = None,
    model: str | None = None,
    tag_turns: bool = False,
    trajectory_samples: int | str = 0,
    golden_threshold: float = 0.92,
) -> dict:
    """Score conversations and return a structured quality report dict.

    Delegates entirely to the SDK. Scope grounding and golden-Q&A matching
    (including the ``golden_eval_summary`` block) now live in the SDK; this
    function just forwards the eval spec.

    Applies the error-shaped preflight before judging (review R1-2 on
    #106: the filter lives at the API boundary, not just the CLI) and
    records what it dropped in ``summary.excluded_error_shaped`` /
    ``summary.truncated_error_turns`` so consumers comparing two reports
    can see when denominators differ (review R1-1 on #106).

    Args:
        conversations: List of conversation dicts from traffic generator.
        eval_spec: Eval spec dict ({scope, ground_truth, golden_qa}). When
            None, the SDK auto-discovers ``eval/data/eval_spec.json``.
        model: Eval model override.
        tag_turns: Run full turn tagger for correction analysis.
        trajectory_samples: Fetch N execution traces from BigQuery.
            Use ``"all"`` to fetch traces for every session.
        golden_threshold: Cosine similarity threshold for golden matching.

    Returns:
        Quality report dict with summary and sessions.

    Raises:
        ValueError: If every record is error-shaped (nothing scoreable).
    """
    conversations, excluded, truncated = exclude_error_shaped(conversations)
    if excluded:
        preview = ", ".join(excluded[:5])
        if len(excluded) > 5:
            preview += f", ... ({len(excluded) - 5} more)"
        logger.warning(
            "Preflight excluded %d error-shaped conversation(s) — "
            "infrastructure failures, not agent answers: %s",
            len(excluded), preview,
        )
    if truncated:
        logger.info(
            "Preflight truncated %d conversation(s) at their first error "
            "turn; completed exchanges are scored: %s",
            len(truncated), ", ".join(truncated[:5]),
        )
    if not conversations:
        raise NothingScoreableError(
            f"No scoreable conversations: all {len(excluded)} records "
            "in the input are error-shaped (infrastructure failures)."
        )

    if _get_sdk().PROJECT_ID is None:
        _get_sdk()._load_config()
    traj_count = trajectory_samples
    if isinstance(trajectory_samples, str) and trajectory_samples.lower() == "all":
        traj_count = len(conversations)

    report = _get_sdk().generate_quality_report_from_conversations(
        conversations, model=model, eval_spec=eval_spec,
        tag_turns=tag_turns, trajectory_samples=traj_count,
        golden_threshold=golden_threshold,
    )
    summary = report.get("summary")
    if isinstance(summary, dict):
        summary["excluded_error_shaped"] = {
            "count": len(excluded), "session_ids": excluded,
        }
        if truncated:
            summary["truncated_error_turns"] = {
                "count": len(truncated), "session_ids": truncated,
            }
    return report


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def write_md_report(report: dict, output_path: str) -> str:
    """Write a human-readable Markdown report next to the JSON output.

    Args:
        report: Quality report dict (summary + sessions).
        output_path: Path to the JSON report file. The .md file is written
            alongside it with the same basename.

    Returns:
        Absolute path to the generated Markdown file.
    """
    s = report["summary"]
    sessions = report.get("sessions", [])

    lines: list[str] = []
    w = lines.append

    w("# Quality Evaluation Report")
    w("")
    w(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w("")

    # --- Summary ---
    w("## Summary")
    w("")
    w("| Metric | Value |")
    w("|--------|-------|")
    w(f"| Total sessions | {s['total_sessions']} |")
    if "excluded_error_shaped" in s:
        w(f"| Excluded error-shaped (infra failures, not in denominator) "
          f"| {s['excluded_error_shaped']['count']} |")
    if "truncated_error_turns" in s:
        w(f"| Truncated at first error turn (completed exchanges scored) "
          f"| {s['truncated_error_turns']['count']} |")
    w(f"| Meaningful | {s['meaningful']} ({s['meaningful_rate']:.1f}%) |")
    w(f"| Unhelpful | {s['unhelpful']} ({s['unhelpful_rate']:.1f}%) |")
    if "knowledge_gap" in s:
        w(f"| &nbsp;&nbsp;↳ Skill gaps (evolution fixes) | {s['skill_gap']} |")
        w(f"| &nbsp;&nbsp;↳ Knowledge gaps (add a fact) "
          f"| {s['knowledge_gap']} |")
        w(f"| &nbsp;&nbsp;↳ Tool gaps (build a tool) "
          f"| {s.get('tool_gap', 0)} |")
        w(f"| **Addressable meaningful rate** (excl. knowledge + tool gaps) "
          f"| **{s.get('addressable_meaningful_rate', 0):.1f}%** |")
    w(f"| Partial | {s.get('partial', 0)} |")
    w(f"| Declined (correct) | {s.get('declined', 0)} |")
    w(f"| Correction rate | {s.get('correction_rate', 0):.1f}% |")
    w(f"| Avg corrections | {s.get('avg_corrections', 0):.1f} |")
    w(f"| Avg tool calls | {s.get('avg_tool_calls', 0):.1f} |")
    w(f"| Avg user turns | {s.get('avg_user_turns', 0):.1f} |")
    w("")

    # --- Failure breakdown: the three fixers ---
    for gap_class, title, blurb in (
        ("knowledge_gap", "Knowledge Gaps (add a fact to existing data)",
         "In-scope questions the agent looked up correctly but its data source "
         "is silent on. Skill evolution cannot invent these facts — a human "
         "adds them to the knowledge base:"),
        ("tool_gap", "Tool Gaps (build a new tool / data source)",
         "Requests no tool can serve — a topic with no data source, or personal "
         "data / actions the agent has no capability for. An engineer must add "
         "a tool:"),
    ):
        questions = [
            sess.get("question", "")
            for sess in report.get("sessions", [])
            if sess.get("failure_class") == gap_class and sess.get("question")
        ]
        if not questions:
            continue
        w(f"### {title}")
        w("")
        w(blurb)
        w("")
        for q in questions[:15]:
            w(f"- {' '.join(q.split())[:160]}")
        if len(questions) > 15:
            w(f"- …and {len(questions) - 15} more")
        w("")

    # --- Quality dimensions ---
    dim_avgs = s.get("dimension_averages", {})
    if dim_avgs:
        w("## Quality Dimensions")
        w("")
        w("| Dimension | Score (0-2) | Rating |")
        w("|-----------|-------------|--------|")
        for dim in ("correctness", "tool_usage", "specificity",
                     "scope_compliance", "first_time_right"):
            val = dim_avgs.get(dim, 0)
            if val >= 1.5:
                rating = "Good"
            elif val >= 1.0:
                rating = "Fair"
            else:
                rating = "Poor"
            w(f"| {dim.replace('_', ' ').title()} | {val:.2f} | {rating} |")
        w("")

    # --- Golden eval summary ---
    gs = s.get("golden_eval_summary")
    if gs:
        w("## Golden Eval Summary")
        w("")
        w("| | Matched | Unmatched |")
        w("|---|---------|-----------|")
        w(f"| Total | {gs['matched']} | {gs['unmatched']} |")
        w(f"| Meaningful | {gs['matched_meaningful']} "
          f"| {gs['unmatched_meaningful']} |")
        w(f"| Unhelpful | {gs['matched_unhelpful']} "
          f"| {gs['unmatched_unhelpful']} |")
        w(f"| Partial | {gs['matched_partial']} "
          f"| {gs['unmatched_partial']} |")
        w(f"| Meaningful rate | {gs['matched_meaningful_rate']:.1f}% "
          f"| {gs['unmatched_meaningful_rate']:.1f}% |")
        w("")

        if gs.get("mismatches"):
            w(f"### Failed Golden-Matched Questions ({len(gs['mismatches'])})")
            w("")
            for mm in gs["mismatches"]:
                w(f"**Q:** {mm['question']}")
                w(f"- Topic: {mm['topic']} "
                  f"(similarity: {mm['similarity']:.2f})")
                w(f"- Expected: {mm['expected_answer'][:300]}")
                w(f"- Actual: {mm['actual_response'][:300]}")
                w("")

    # --- Category breakdown ---
    categories: dict[str, list[dict]] = {}
    for sess in sessions:
        cat = (sess.get("metrics", {})
               .get("response_usefulness", {})
               .get("category", "unknown"))
        categories.setdefault(cat, []).append(sess)

    if categories:
        w("## Category Breakdown")
        w("")
        w("| Category | Count | % |")
        w("|----------|-------|---|")
        total = len(sessions) or 1
        for cat in ("meaningful", "declined", "partial", "unhelpful", "unknown"):
            items = categories.get(cat, [])
            if items:
                w(f"| {cat.title()} | {len(items)} "
                  f"| {len(items) / total * 100:.1f}% |")
        w("")

    # --- Unhelpful sessions ---
    unhelpful = categories.get("unhelpful", [])
    if unhelpful:
        w(f"## Unhelpful Sessions ({len(unhelpful)})")
        w("")
        for sess in unhelpful:
            q = sess.get("question", "N/A")
            resp = sess.get("response",
                            sess.get("final_response", "N/A"))[:400]
            justification = (sess.get("metrics", {})
                             .get("response_usefulness", {})
                             .get("justification", ""))
            w(f"### Q: {q}")
            w("")
            w(f"**Response:** {resp}")
            w("")
            if justification:
                w(f"**Why unhelpful:** {justification}")
                w("")
            dims = sess.get("quality_scores", {})
            if dims:
                low = [
                    f"{d.replace('_', ' ')}={v['score']}"
                    for d, v in dims.items()
                    if isinstance(v, dict) and v.get("score", 2) < 1.5
                ]
                if low:
                    w(f"**Low dimensions:** {', '.join(low)}")
                    w("")

    # --- Partial sessions ---
    partial = categories.get("partial", [])
    if partial:
        w(f"## Partial Sessions ({len(partial)})")
        w("")
        for sess in partial[:10]:
            q = sess.get("question", "N/A")
            justification = (sess.get("metrics", {})
                             .get("response_usefulness", {})
                             .get("justification", ""))
            w(f"- **Q:** {q}")
            if justification:
                w(f"  - {justification[:200]}")
        w("")

    # Write file
    md_path = os.path.splitext(output_path)[0] + ".md"
    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return os.path.abspath(md_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Score traffic generator conversations using SDK evaluation"
    )
    parser.add_argument(
        "--input", "-i",
        default=None,
        help="Path to traffic results JSON (conversations list)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output quality report JSON path",
    )
    parser.add_argument(
        "--eval-spec",
        type=str,
        default=None,
        dest="eval_spec",
        help="Path to eval_spec.json ({scope, ground_truth, golden_qa}). "
        "Auto-discovered from eval/data/eval_spec.json. Use 'none' to disable.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Eval model override (default: EVAL_MODEL_ID or gemini-2.5-flash)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Also generate a Markdown report alongside the JSON output.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Max parallel Gemini API calls (default: 10).",
    )
    parser.add_argument(
        "--tag-turns",
        action="store_true",
        default=False,
        help="Run full turn tagger to classify user turns and identify "
        "correction boundaries / sub-trajectories.",
    )
    parser.add_argument(
        "--trajectory-samples",
        type=str,
        default="0",
        metavar="N",
        help="Fetch N execution traces from BigQuery and include in report. "
        "Prioritizes unhelpful and correction sessions. "
        "Use 'all' to fetch traces for every session.",
    )
    parser.add_argument(
        "--golden-threshold",
        type=float,
        default=0.92,
        metavar="FLOAT",
        help="Cosine similarity threshold for golden eval matching "
        "(default: 0.92). Lower values match more aggressively.",
    )
    parser.add_argument(
        "--report-from-json",
        type=str,
        default=None,
        metavar="PATH",
        help="Generate a Markdown report from an existing JSON quality report "
        "file (no scoring). Writes .md alongside the JSON.",
    )
    parser.add_argument(
        "--compare",
        nargs="+",
        metavar="PATH[:LABEL]",
        help="Compare multiple quality report files side by side.",
    )
    args = parser.parse_args()

    if args.compare:
        compare_reports(args.compare)
        return

    if args.report_from_json:
        with open(args.report_from_json) as f:
            existing = json.load(f)
        # Re-derive the skill-gap / knowledge-gap split from the per-session
        # dimensions already in the report (deterministic, no re-scoring), then
        # persist it so the JSON and Markdown both carry the breakdown.
        _get_sdk()._classify_failures(existing)
        with open(args.report_from_json, "w") as f:
            json.dump(existing, f, indent=2, default=str)
        md_path = write_md_report(existing, args.report_from_json)
        print(f"Markdown report: {md_path}")
        return

    if not args.input:
        parser.error("--input is required when not using --compare")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    with open(args.input) as f:
        data = json.load(f)

    conversations = data.get("conversations", [])
    if not conversations:
        print("No conversations found in input file.")
        sys.exit(1)

    logger.info("Scoring %d conversations (before preflight)...",
                len(conversations))

    # "all" is resolved inside generate_quality_report against the
    # post-preflight count; pass it through untouched.
    traj_samples_raw = args.trajectory_samples.strip().lower()
    traj_count = traj_samples_raw if traj_samples_raw == "all" \
        else int(traj_samples_raw)

    # Resolve eval spec: explicit --eval-spec, else auto-discover; the SDK does
    # the same auto-discovery, but loading here lets us log what was used.
    eval_spec = _get_sdk()._load_eval_spec(getattr(args, "eval_spec", None))
    if eval_spec:
        logger.info(
            "Eval spec: scope=%s, ground_truth=%s, golden_qa=%d",
            bool(eval_spec.get("scope")),
            bool(eval_spec.get("ground_truth")),
            len(eval_spec.get("golden_qa") or []),
        )

    try:
        report = generate_quality_report(
            conversations, eval_spec=eval_spec, model=args.model,
            tag_turns=args.tag_turns, trajectory_samples=traj_count,
            golden_threshold=args.golden_threshold,
        )
    except NothingScoreableError as e:
        print(e)
        sys.exit(1)

    output_path = args.output or os.path.join(
        os.path.dirname(__file__), "quality_report.json"
    )
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Quality report saved to %s", output_path)

    if args.report:
        md_path = write_md_report(report, output_path)
        logger.info("Markdown report saved to %s", md_path)

    golden_summary = report.get("summary", {}).get("golden_eval_summary")
    if golden_summary:
        print("\n--- Golden Eval Summary ---")
        print(f"{'':30s} {'Matched':>10s} {'Unmatched':>10s}")
        print(f"{'Total':30s} {golden_summary['matched']:>10d} "
              f"{golden_summary['unmatched']:>10d}")
        print(f"{'Meaningful':30s} {golden_summary['matched_meaningful']:>10d} "
              f"{golden_summary['unmatched_meaningful']:>10d}")
        print(f"{'Unhelpful':30s} {golden_summary['matched_unhelpful']:>10d} "
              f"{golden_summary['unmatched_unhelpful']:>10d}")
        print(f"{'Partial':30s} {golden_summary['matched_partial']:>10d} "
              f"{golden_summary['unmatched_partial']:>10d}")
        print(f"{'Meaningful rate':30s} "
              f"{golden_summary['matched_meaningful_rate']:>9.1f}% "
              f"{golden_summary['unmatched_meaningful_rate']:>9.1f}%")
        if golden_summary["mismatches"]:
            print(f"\n--- Failed Golden-Matched Questions "
                  f"({len(golden_summary['mismatches'])}) ---")
            for mm in golden_summary["mismatches"]:
                print(f"\n  Q: {mm['question']}")
                print(f"  Topic: {mm['topic']} "
                      f"(similarity: {mm['similarity']:.2f})")
                print(f"  Expected: {mm['expected_answer'][:200]}")
                print(f"  Actual:   {mm['actual_response'][:200]}")


if __name__ == "__main__":
    main()
