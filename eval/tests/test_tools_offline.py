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
        {"session_id": "err-resp",
         "response": "ERROR: 503 Service Unavailable", "errors": 0},
        {"session_id": "err-turn", "errors": 0, "conversation": [
            {"role": "user", "text": "hi"},
            {"role": "system", "text": "ERROR: timeout"},
        ]},
        {"session_id": "ok-2", "conversation": [
            {"role": "user", "text": "quoting"},
            {"role": "agent", "text": "The log line says 'ERROR: x' means..."},
        ]},
        {"session_id": "partial", "errors": 1,
         "final_response": "Your balance is 20 days.",
         "conversation": [
             {"role": "user", "text": "balance?"},
             {"role": "agent", "text": "Your balance is 20 days."},
             {"role": "user", "text": "and next year?"},
             {"role": "system", "text": "ERROR: 503 quota"},
         ]},
    ]
    kept, excluded, truncated = sc.exclude_error_shaped(convs)
    assert [c["session_id"] for c in kept] == ["ok-1", "ok-2", "partial"]
    assert excluded == ["err-resp", "err-turn"]
    assert truncated == ["partial"]
    partial = kept[-1]
    # Truncated copy: error turn gone, completed exchanges kept, original
    # record untouched.
    assert [t["text"] for t in partial["conversation"]] == [
        "balance?", "Your balance is 20 days.", "and next year?"]
    assert partial["preflight_truncated"] is True and not partial["errors"]
    assert convs[-1]["errors"] == 1 and len(convs[-1]["conversation"]) == 4
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
    from eval.scoring import score_conversations as sc
    import pytest

    monkeypatch.setattr(sc, "_sdk", _FakeSDK)
    with pytest.raises(ValueError, match="error-shaped"):
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
