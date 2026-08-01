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

"""Adapter tests: evolve.py delegates the algorithm to the SDK engine.

No network/model calls — only the SDK module import (ensure_sdk clones the
pinned SDK_REPO/SDK_BRANCH on first run) and pure functions.
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)

from agents.workflow.skill_evolution_agent import evolve as adapter


def test_engine_is_the_sdk_module():
    engine = adapter._engine()
    # The single source of truth: the loaded module is the SDK's script.
    assert engine.__name__ == "skill_evolution"
    assert "scripts" in os.path.abspath(engine.__file__)


def test_reexports_delegate_to_engine():
    engine = adapter._engine()
    session = {
        "metrics": {"response_usefulness": {"category": "unhelpful"}},
        "question": "How many PTO days?",
        "response": "contact HR",
    }
    assert adapter.format_trajectory(session) == engine.format_trajectory(session)
    assert adapter.sanitize_adk_vars("{foo}") == "<foo>"
    report = {"sessions": [session]}
    successes, failures = adapter.partition_trajectories(report)
    assert not successes and len(failures) == 1


def test_engine_has_the_host_hooks():
    # The pinned SDK branch must carry the three host seams the adapter uses.
    import inspect

    engine = adapter._engine()
    evolve_params = inspect.signature(engine.evolve_skill).parameters
    assert "error_analyst_fn" in evolve_params
    assert "incumbent_score" in evolve_params
    select_params = inspect.signature(engine.select_candidate).parameters
    assert "incumbent_score" in select_params


def test_version_label_from_frontmatter():
    assert adapter._version_label('---\nversion: "0"\n---\nbody') == "v1"
    assert adapter._version_label('---\nversion: "2"\n---\nbody') == "v3"
    assert adapter._version_label("no frontmatter") == "v1"


def test_stride_sample_respects_cap(monkeypatch):
    def _fail(question):
        return {
            "metrics": {"response_usefulness": {"category": "unhelpful"}},
            "question": question,
        }

    report = {"sessions": [_fail(f"q{i}") for i in range(10)]}
    monkeypatch.setenv("EVOLUTION_MAX_ANALYSTS", "4")
    trimmed = adapter._stride_sample_failures(report)
    assert len(trimmed["sessions"]) == 4
    # Stride keeps coverage across the distribution, not just the head.
    questions = [s["question"] for s in trimmed["sessions"]]
    assert questions[0] == "q0" and questions[-1] not in ("q1", "q2", "q3")

    monkeypatch.delenv("EVOLUTION_MAX_ANALYSTS")
    assert adapter._stride_sample_failures(report) is report


def test_auto_candidates_rate_tiers(monkeypatch):
    monkeypatch.delenv("EVOLUTION_CANDIDATES", raising=False)
    assert adapter._auto_candidates({"meaningful_rate": 95}) == 1
    assert adapter._auto_candidates({"meaningful_rate": 85}) == 3
    assert adapter._auto_candidates({"meaningful_rate": 60}) == 5
    monkeypatch.setenv("EVOLUTION_CANDIDATES", "2")
    assert adapter._auto_candidates({"meaningful_rate": 60}) == 2


def test_flatten_candidates(tmp_path):
    cand_dir = tmp_path / "candidates"
    sub = cand_dir / "v1_candidates"
    sub.mkdir(parents=True)
    (sub / "candidate_1.md").write_text("one")
    (sub / "candidate_2_SELECTED.md").write_text("two")

    adapter._flatten_candidates(str(cand_dir))

    assert (cand_dir / "candidate_1.md").read_text() == "one"
    # The winner's flat copy drops the _SELECTED tag (existing contract).
    assert (cand_dir / "candidate_2.md").read_text() == "two"
