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

"""Latency report — thin shim that delegates to the SDK.

The SDK's ``latency_report.py`` is the single source of truth.
This file only adds SDK discovery via ``ensure_sdk`` and forwards
to the SDK's ``main()``.

Usage:
    python scripts/utils/latency_report.py                    # latest trace
    python scripts/utils/latency_report.py --limit 5          # last 5 traces
    python scripts/utils/latency_report.py --session <id>     # specific session
    python scripts/utils/latency_report.py --time-period 1h   # traces from last hour
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)

from ensure_sdk import import_sdk_module  # noqa: E402

if __name__ == "__main__":
    import_sdk_module("latency_report").main()
