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

"""Offline unit tests for the code findings in reviews #53 and #54.

No network, no model calls, no gcloud. Each test pins a specific defect
from those reviews so it cannot regress silently again.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)

from agents.workflow.quality_agent import tools as quality_tools
from agents.workflow.skill_evolution_agent import coevolve
from agents.workflow.skill_evolution_agent import tools as evolution_tools


# --- #53 finding 1: GitHub App issue path crashed with NameError ------------


def test_create_github_issue_app_path_no_nameerror(monkeypatch):
    # The preferred (GitHub App) branch passed an undefined `body` variable
    # and crashed before creating any issue. Reproduction from the review,
    # asserting the constructed body actually reaches the App client.
    captured = {}

    def fake_pygithub(title, body, labels, **kwargs):
        captured["title"] = title
        captured["body"] = body
        return {"status": "created", "number": 1}

    monkeypatch.setattr(quality_tools, "_app_secrets_available", lambda: True)
    monkeypatch.setattr(quality_tools, "_find_agy", lambda: None)
    monkeypatch.setattr(quality_tools, "_create_issue_pygithub", fake_pygithub)

    result = quality_tools.create_github_issue(
        "prompt-gap", "policy_agent", "demo", "root", [], "fix", [], {},
    )
    assert result.get("status") == "created"
    assert "## Metadata" in captured["body"]


# --- #53 finding 6: missing meaningful_rate rendered as a fake 100% ---------


def test_issue_body_derives_rate_from_counts():
    body = quality_tools._build_issue_body(
        "prompt-gap", "policy_agent", "pto", "high", "root", [], "fix", [],
        summary={"total_sessions": 80, "meaningful": 20},
    )
    assert "| Meaningful rate | 25.0% |" in body


def test_issue_body_unknown_rate_instead_of_fake_100():
    # A summary with neither a rate nor counts must say "unknown" — the
    # old default invented "100%" next to dozens of unhelpful sessions.
    body = quality_tools._build_issue_body(
        "prompt-gap", "policy_agent", "pto", "high", "root", [], "fix", [],
        summary={},
    )
    assert "| Meaningful rate | unknown |" in body
    assert "unknown%" not in body
    assert "100%" not in body


def test_issue_body_keeps_explicit_rate():
    body = quality_tools._build_issue_body(
        "prompt-gap", "policy_agent", "pto", "high", "root", [], "fix", [],
        summary={"meaningful_rate": 23.1},
    )
    assert "| Meaningful rate | 23.1% |" in body


# --- #54 finding 7: git stderr leaked the embedded GitHub token -------------


def test_mask_tokens_scrubs_git_remote_errors(monkeypatch):
    token = "ghs_secret1234567890"
    monkeypatch.setenv("GH_TOKEN", token)
    stderr = (
        "fatal: unable to access "
        f"'https://x-access-token:{token}@github.com/o/r.git/': error 502"
    )
    masked = evolution_tools._mask_tokens(stderr)
    assert token not in masked
    assert "***" in masked


def test_mask_tokens_handles_empty_and_unset(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert evolution_tools._mask_tokens("") == ""
    assert evolution_tools._mask_tokens("plain error") == "plain error"


# --- #54 finding 8: len() on int failure counts crashed the summary ---------


def test_failure_count_accepts_both_bottleneck_shapes():
    # Live detect_bottleneck() carries lists; the target-bound and
    # precomputed paths carry plain ints. Both must tally.
    assert coevolve._failure_count(0) == 0
    assert coevolve._failure_count(7) == 7
    assert coevolve._failure_count([]) == 0
    assert coevolve._failure_count([{"q": "a"}, {"q": "b"}]) == 2


# --- #54 finding 9: incumbent must refresh between sequential agents --------


def test_incumbent_refresh_between_sequential_agents(tmp_path):
    # Comparing agent 2's candidates against pre-agent-1 V0 let a system
    # regression clear a stale guard. After agent 1 deploys, the bar the
    # next agent must clear is the score evolve() recorded in
    # evolved_score.json — not the original baseline.
    import json as _json

    v0_baseline = 55.1

    # Agent 1 has not deployed yet: no file -> baseline unchanged.
    assert coevolve._refresh_incumbent(str(tmp_path), v0_baseline) == v0_baseline

    # Agent 1 deploys a winner: the recorded score becomes the new bar.
    (tmp_path / "evolved_score.json").write_text(
        _json.dumps({"meaningful_rate": 85.4})
    )
    assert coevolve._refresh_incumbent(str(tmp_path), v0_baseline) == 85.4

    # No output_dir (dry paths) keeps the current bar.
    assert coevolve._refresh_incumbent(None, v0_baseline) == v0_baseline

    # A null rate or a corrupt file never silently drops the bar.
    (tmp_path / "evolved_score.json").write_text(
        _json.dumps({"meaningful_rate": None})
    )
    assert coevolve._refresh_incumbent(str(tmp_path), 85.4) == 85.4
    (tmp_path / "evolved_score.json").write_text("{not json")
    assert coevolve._refresh_incumbent(str(tmp_path), 85.4) == 85.4


# --- retrofit review R1-2 (#105): error-shaped answers must never be judged --


def test_error_shaped_preflight_excludes_infrastructure_failures():
    # The generator writes "ERROR: {e}" transcripts and errors=1 records on
    # send failures; a judge scores those as unhelpful, producing fake rates.
    # Records with no usable agent answer are excluded; partly-successful
    # multi-turn records are truncated at the error turn and kept (R1-3).
    from eval.scoring import score_conversations as sc

    convs = [
        {"session_id": "ok-1", "response": "You have 20 PTO days.",
         "errors": 0},
        # Generator shape: the flag is always set alongside the ERROR
        # response (main.py:573-575).
        {"session_id": "err-resp",
         "response": "ERROR: 503 Service Unavailable", "errors": 1},
        # A genuine agent ANSWER that opens with "ERROR:" (quoting a code
        # back to the user) has no flag and no error turn — it stays in
        # the denominator (R5-4).
        {"session_id": "ok-3-error-quote", "errors": 0,
         "response": "ERROR: 503 in the gateway log means the upstream timed out."},
        {"session_id": "err-turn", "errors": 0, "conversation": [
            {"role": "user", "text": "hi"},
            {"role": "system", "text": "ERROR: timeout"},
        ]},
        {"session_id": "ok-2", "conversation": [
            {"role": "user", "text": "quoting"},
            {"role": "agent", "text": "The log line says 'ERROR: x' means..."},
        ]},
        # errors flag set but no error turn to cut at — the generator
        # always writes one, so this record is corrupt; excluded rather
        # than kept with fabricated conversation/user_turns (R3-5).
        {"session_id": "flag-only", "response": "fine text", "errors": 1},
        {"session_id": "partial", "errors": 1, "user_turns": 3,
         "corrections": 2, "verifications": 1,
         "final_response": "Your balance is 20 days.",
         "conversation": [
             {"role": "user", "text": "balance?"},
             {"role": "agent", "text": "It is 25 days."},
             {"role": "user", "text": "no, check again", "tag": "CORRECTION"},
             {"role": "agent", "text": "Your balance is 20 days."},
             {"role": "user", "text": "sure?", "tag": "VERIFY"},
             {"role": "system", "text": "ERROR: 503 quota"},
         ]},
        # ERROR arrived as system *text* (errors=0) before any completed
        # exchange; the recovery answer after it is what final_response
        # points at. Scoring the pre-error stub would disagree with its
        # own final answer, so the record is excluded (R2-4).
        {"session_id": "err-then-recovered", "errors": 0,
         "final_response": "Recovered answer.",
         "conversation": [
             {"role": "user", "text": "hello?"},
             {"role": "system", "text": "ERROR: bad gateway"},
             {"role": "user", "text": "hello again?"},
             {"role": "agent", "text": "Recovered answer."},
         ]},
    ]
    kept, excluded, truncated = sc.exclude_error_shaped(convs)
    assert [c["session_id"] for c in kept] == [
        "ok-1", "ok-3-error-quote", "ok-2", "partial"]
    assert excluded == ["err-resp", "err-turn", "flag-only",
                        "err-then-recovered"]
    assert truncated == ["partial"]
    partial = kept[-1]
    # Truncated copy ends on the last completed exchange: the error turn
    # AND the unanswered trailing user turn are gone (R2-1); user_turns,
    # final_response, and the tag-derived corrections/verifications
    # counters recomputed from the kept turns (R3-3); the original record
    # is untouched.
    assert [t["text"] for t in partial["conversation"]] == [
        "balance?", "It is 25 days.", "no, check again",
        "Your balance is 20 days."]
    assert partial["user_turns"] == 2
    assert partial["corrections"] == 1  # the VERIFY turn was cut
    assert partial["verifications"] == 0
    assert partial["final_response"] == "Your balance is 20 days."
    assert partial["preflight_truncated"] is True and not partial["errors"]
    original = next(c for c in convs if c["session_id"] == "partial")
    assert original["errors"] == 1 and len(original["conversation"]) == 6
    assert original["user_turns"] == 3 and original["corrections"] == 2
    # Idempotent: a second pass finds nothing error-shaped in the output.
    kept2, excluded2, truncated2 = sc.exclude_error_shaped(kept)
    assert (kept2, excluded2, truncated2) == (kept, [], [])


# --- #106 R1-1: the exclusion record must reach the report artifact ---------


class _FakeSDK:
    PROJECT_ID = "offline-test"

    @staticmethod
    def generate_quality_report_from_conversations(convs, **kwargs):
        return {"summary": {"total_sessions": len(convs)}, "sessions": []}


def test_exclusion_record_reaches_report_summary(monkeypatch):
    # A report scored after preflight exclusions must say so in the JSON:
    # comparing rates over different denominators silently was the bug.
    from eval.scoring import score_conversations as sc

    monkeypatch.setattr(sc, "_sdk", _FakeSDK)
    report = sc.generate_quality_report([
        {"session_id": "ok-1", "response": "fine", "errors": 0},
        {"session_id": "err-1", "response": "ERROR: 503", "errors": 1},
    ])
    assert report["summary"]["total_sessions"] == 1
    assert report["summary"]["excluded_error_shaped"] == {
        "count": 1, "session_ids": ["err-1"]}
    assert "truncated_error_turns" not in report["summary"]


def test_all_error_shaped_raises_instead_of_scoring(monkeypatch):
    # A dedicated exception type, so callers (and the CLI) can tell
    # nothing-scoreable apart from a genuine scoring ValueError (R2-3).
    from eval.scoring import score_conversations as sc
    import pytest

    monkeypatch.setattr(sc, "_sdk", _FakeSDK)
    with pytest.raises(sc.NothingScoreableError, match="error-shaped"):
        sc.generate_quality_report(
            [{"session_id": "err-1", "response": "ERROR: 503", "errors": 1}]
        )


def test_md_report_carries_exclusion_row(tmp_path):
    from eval.scoring import score_conversations as sc

    report = {
        "summary": {
            "total_sessions": 8, "meaningful": 6, "meaningful_rate": 75.0,
            "unhelpful": 2, "unhelpful_rate": 25.0,
            "excluded_error_shaped": {"count": 2, "session_ids": ["a", "b"]},
            "truncated_error_turns": {"count": 1, "session_ids": ["c"]},
        },
        "sessions": [],
    }
    md_path = sc.write_md_report(report, str(tmp_path / "report.json"))
    md = open(md_path).read()
    assert "| Excluded error-shaped (infra failures, not in denominator) | 2 |" in md
    assert "| Truncated at first error turn (completed exchanges scored) | 1 |" in md


def test_excluded_count_guards_candidate_selection(tmp_path, monkeypatch):
    # #106 R3-1 (and its tools.py sister): a report that lost records to
    # the preflight has a shrunken denominator; selection must be able to
    # see that and skip it instead of comparing raw rates.
    import json as _json

    monkeypatch.setenv("EVOLUTION_PUBLISH", "0")

    # Baseline report with a failure session
    baseline = tmp_path / "baseline_quality_report.json"
    baseline.write_text(_json.dumps({
        "summary": {"meaningful_rate": 0.0},
        "sessions": [
            {
                "question": "q1",
                "metrics": {"response_usefulness": {"category": "unhelpful"}},
                "response": "bad"
            }
        ]
    }))

    quota_hit = tmp_path / "candidate_1_report.json"
    quota_hit.write_text(_json.dumps({
        "summary": {
            "meaningful_rate": 100.0,
            "excluded_error_shaped": {"count": 3, "session_ids": ["a", "b", "c"]},
        },
        "sessions": [
            {
                "question": "q1",
                "metrics": {"response_usefulness": {"category": "meaningful"}},
                "response": "excellent candidate 1",
                "answered_by": "policy_agent"
            }
        ]
    }))
    clean = tmp_path / "candidate_2_report.json"
    clean.write_text(_json.dumps({
        "summary": {
            "meaningful_rate": 88.0,
            "excluded_error_shaped": {"count": 0, "session_ids": []},
        },
        "sessions": [
            {
                "question": "q1",
                "metrics": {"response_usefulness": {"category": "meaningful"}},
                "response": "excellent candidate 2",
                "answered_by": "policy_agent"
            }
        ]
    }))
    legacy = tmp_path / "old_report.json"
    legacy.write_text(_json.dumps({"summary": {"meaningful_rate": 90.0}}))

    assert evolution_tools._excluded_count(str(quota_hit)) == 3
    assert evolution_tools._excluded_count(str(clean)) == 0
    assert evolution_tools._excluded_count(str(legacy)) == 0  # pre-key report
    assert evolution_tools._excluded_count(str(tmp_path / "missing.json")) == 0

    # Execute extract_regression_cases: candidate 1 is skipped, candidate 2 wins and its session is extracted
    res = evolution_tools.extract_regression_cases(run_dir=str(tmp_path))
    assert res["status"] == "success"

    golden_file = tmp_path / "golden_evals.json"
    assert golden_file.exists()
    golden_content = _json.loads(golden_file.read_text())
    cases = golden_content.get("eval_cases", [])
    assert "excellent candidate 2" in cases[0]["expected_answer"]
    assert "excellent candidate 1" not in cases[0]["expected_answer"]


# --- #106 R6-5: pins for the R5/R6 denominator machinery -------------------


def test_exclusion_footer_mechanical():
    # R5-1: the disclosure appended to LLM-written bodies is deterministic.
    assert evolution_tools._exclusion_footer(0, 0) == ""
    footer = evolution_tools._exclusion_footer(1, 3)
    assert "DENOMINATORS DIFFER" in footer
    assert "1 baseline" in footer and "3 evolved" in footer


def test_collect_metrics_surfaces_exclusions_when_all_shrunken(tmp_path):
    # R5-2: with every candidate report shrunken, the best shrunken one is
    # used and its non-zero exclusion count reaches the metrics dict —
    # never "0 excluded" against a "?%" rate.
    import json as _json

    (tmp_path / "candidate_1_report.json").write_text(_json.dumps({
        "summary": {
            "meaningful_rate": 90.0, "unhelpful_rate": 10.0,
            "excluded_error_shaped": {"count": 2, "session_ids": ["a", "b"]},
        }}))
    m = evolution_tools._collect_quality_metrics(str(tmp_path), "v1")
    assert m["evolved_excl"] == 2
    assert m["evolved_meaningful"] == "90.0"


def test_compare_versions_guards_denominators(tmp_path):
    # R6-2: deltas are suppressed across shrunken reports and best_version
    # prefers clean denominators over a shrunken 100%.
    import json as _json

    def w(name, total, meaningful, rate, excl=0):
        summary = {"total_sessions": total, "meaningful": meaningful,
                   "meaningful_rate": rate, "unhelpful": total - meaningful,
                   "unhelpful_rate": round(100 - rate, 1)}
        if excl:
            summary["excluded_error_shaped"] = {
                "count": excl, "session_ids": ["x"] * excl}
        (tmp_path / name).write_text(_json.dumps({"summary": summary}))

    w("v0_quality_report.json", 20, 15, 75.0)
    w("v1_quality_report.json", 16, 16, 100.0, excl=4)
    w("v2_quality_report.json", 20, 17, 85.0)

    res = evolution_tools.compare_versions(str(tmp_path))
    assert res["best_version"] == "v2"
    v1 = next(v for v in res["versions"] if v["version"] == "v1")
    assert v1["excluded"] == 4
    assert v1["delta"] is None
    assert "(4 excluded)" in res["table"]


def test_unmeasurable_winner_records_null_marker(tmp_path):
    # R6-4: an unmeasurable winner writes an explicit null marker instead
    # of leaving the previous agent's score on disk; compare_versions
    # treats it like a shrunken report.
    import json as _json

    from agents.workflow.skill_evolution_agent import evolve as evolve_mod

    cand = tmp_path / "candidates"
    cand.mkdir()
    evolve_mod._record_evolved_score(str(cand), None, unmeasurable=True)
    es = _json.loads((tmp_path / "evolved_score.json").read_text())
    assert es["meaningful_rate"] is None
    assert es["unmeasurable"] is True

    (tmp_path / "v0_quality_report.json").write_text(_json.dumps({
        "summary": {"total_sessions": 20, "meaningful": 15,
                    "meaningful_rate": 75.0, "unhelpful": 5,
                    "unhelpful_rate": 25.0}}))
    res = evolution_tools.compare_versions(str(tmp_path))
    ev = next(v for v in res["versions"] if v["version"] == "evolved")
    # R7-1: the marker renders as unmeasured, never as a measured 0% on
    # a fabricated session count, and it can never be best_version.
    assert ev["unmeasurable"] is True
    assert ev["meaningful_rate"] is None
    assert ev["delta"] is None
    assert "n/a (unmeasurable)" in res["table"]
    assert res["best_version"] == "v0"
