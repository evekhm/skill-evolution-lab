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
