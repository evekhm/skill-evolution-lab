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

"""Quality report — thin shim that delegates to the SDK.

The SDK's ``quality_report.py`` is the single source of truth for all
evaluation logic, metric definitions, conversation extraction, and
LLM-inferred correction counting.  This file only adds:

  1. SDK discovery (SDK_DIR env, sibling-repo, or auto-clone via ensure_sdk).
  2. Re-exports of the functions used by tools.py.
  3. A compatibility wrapper for ``_build_scope_context`` that loads
     agent_context.json automatically (the SDK version requires it to
     be passed in).

Usage (CLI — same interface as the SDK script):
    python quality_report.py                      # evaluate last 100 sessions
    python quality_report.py --limit 50           # evaluate last 50 sessions
    python quality_report.py --time-period 7d     # evaluate last 7 days
    python quality_report.py --report             # also generate markdown report
    python quality_report.py --no-eval            # browse Q&A only
    python quality_report.py --output-json r.json # write structured JSON output
"""

import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

_script_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_script_dir, "../../.."))

# Add repo root to sys.path so ``import ensure_sdk`` works both locally
# (repo root) and in Docker (ensure_sdk.py copied into /app).
for _candidate in [_repo_root, "/app"]:
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from ensure_sdk import import_sdk_module  # noqa: E402

_sdk = import_sdk_module("quality_report")

# ---------------------------------------------------------------------------
# Re-exports used by tools.py
# ---------------------------------------------------------------------------
run_evaluation = _sdk.run_evaluation
_build_json_output = _sdk._build_json_output
_load_config = _sdk._load_config

# ---------------------------------------------------------------------------
# Compatibility wrapper for _build_scope_context
#
# The SDK version of _build_scope_context(config) requires the caller to
# pass the agent_context dict.  The local code calls it with no args and
# expects it to auto-load agent_context.json.  We wrap it here for compat.
# ---------------------------------------------------------------------------


def _load_agent_context():
    """Load agent context from eval/data/agent_context.json if present."""
    for base in [_repo_root, _script_dir]:
        context_path = os.path.join(base, "eval", "data", "agent_context.json")
        if os.path.isfile(context_path):
            with open(context_path) as f:
                return json.load(f)
    return None


def _build_scope_context(config=None):
    """Build scope context string for the LLM judge.

    Compatible with callers that pass no arguments (loads agent_context.json)
    and callers that pass the config dict directly.
    """
    if config is None:
        config = _load_agent_context()
    return _sdk._build_scope_context(config)


# ---------------------------------------------------------------------------
# CLI — delegate to the SDK's main()
# ---------------------------------------------------------------------------
main = _sdk.main

if __name__ == "__main__":
    main()
