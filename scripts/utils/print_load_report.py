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

"""Pretty-print a load test report with per-topic breakdown.

Usage:
    uv run python3 scripts/utils/print_load_report.py eval/load_test_report.json
"""

import argparse
import json
import sys
from collections import Counter


def print_report(report_path: str) -> None:
    """Print a formatted summary of a load test report."""
    with open(report_path) as f:
        report = json.load(f)

    s = report["summary"]
    print(f"  Questions:       {s['total']}")
    print(f"  Meaningful:      {s['meaningful']}/{s['total']} ({s['meaningful_rate']}%)")
    print(f"  Verdicts:        {s.get('verdicts', {})}")
    print(f"  Errors:          {s['errors']}")
    print(f"  Avg latency:     {s['avg_latency_ms']}ms")
    print(f"  P95 latency:     {s['p95_latency_ms']}ms")
    print()

    # Per-topic breakdown
    topics: Counter = Counter()
    topic_pass: Counter = Counter()
    for res in report["results"]:
        t = res.get("topic", "unknown")
        topics[t] += 1
        if res["meaningful"]:
            topic_pass[t] += 1

    print("  Per-topic breakdown:")
    for t in sorted(topics):
        total = topics[t]
        passed = topic_pass[t]
        pct = round(passed / total * 100) if total else 0
        print(f"    {t:20s}  {passed}/{total} ({pct}%)")


def main():
    parser = argparse.ArgumentParser(description="Print load test report summary")
    parser.add_argument("report_file", help="Path to load_test_report.json")
    args = parser.parse_args()

    print_report(args.report_file)


if __name__ == "__main__":
    main()
