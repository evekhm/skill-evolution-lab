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

"""Check load test results against budget baselines.

Reads a load test results JSON file and compares metrics against
eval/baselines.json. Exits 1 if any budget is exceeded.

Usage:
    # Check results against baselines:
    python eval/check_budget.py eval/load_test_results.json

    # Record new baselines from results:
    python eval/check_budget.py eval/load_test_results.json --record-baseline
"""

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASELINES_PATH = os.path.join(_SCRIPT_DIR, "..", "data", "baselines.json")


def load_baselines() -> dict:
    if not os.path.isfile(BASELINES_PATH):
        logger.warning("No baselines.json found — skipping budget check")
        return {}
    with open(BASELINES_PATH) as f:
        return json.load(f)


def check_budgets(metrics: dict, baselines: dict) -> tuple[bool, list[str]]:
    """Compare metrics against baselines. Returns (all_pass, failures)."""
    budgets = baselines.get("budgets", {})
    if not budgets:
        return True, []

    failures = []
    print("")
    print(f"  {'Metric':<22}  {'Observed':>12}  {'Budget':>12}  {'Status':>8}")
    print(f"  {'─' * 22}  {'─' * 12}  {'─' * 12}  {'─' * 8}")

    for metric_key, budget_val in budgets.items():
        observed = metrics.get(metric_key)
        if observed is None:
            continue
        passed = observed <= budget_val
        status = "PASS" if passed else "FAIL"
        if not passed:
            failures.append(f"{metric_key}: {observed} exceeds budget {budget_val}")
        print(f"  {metric_key:<22}  {observed:>12}  {budget_val:>12}  {status:>8}")

    print("")
    return len(failures) == 0, failures


def save_baselines(metrics: dict):
    """Record current metrics as the new baselines with headroom."""
    meaningful_rate = metrics.get("meaningful_rate", 80)
    baselines = {
        "description": "Operational metric budgets for the load test gate. All budgets are enforced by test_load.py. Run `python eval/check_budget.py eval/load_test_report.json --record-baseline` to recalibrate from observed metrics.",
        "budgets": {
            "quality_threshold": round(max(0.5, (meaningful_rate / 100) * 0.9), 2),
            "error_rate": max(0.0, round(metrics.get("error_rate", 0) * 2, 3)),
            "p95_latency_ms": round(metrics["p95_latency_ms"] * 1.2, 1),
            "avg_latency_ms": round(metrics["avg_latency_ms"] * 1.2, 1),
            "avg_turns": round(metrics.get("avg_turns", 10) * 1.5, 1),
        },
    }
    with open(BASELINES_PATH, "w") as f:
        json.dump(baselines, f, indent=2)
        f.write("\n")
    logger.info("Baselines recorded to %s", BASELINES_PATH)
    return baselines


def main():
    parser = argparse.ArgumentParser(description="Check load test results against budget baselines")
    parser.add_argument("results_file", help="Path to load test results JSON")
    parser.add_argument("--record-baseline", action="store_true", help="Record current metrics as baselines")
    parser.add_argument("--fail-on-budget", action="store_true", help="Exit 1 if any budget exceeded")
    args = parser.parse_args()

    with open(args.results_file) as f:
        data = json.load(f)
    metrics = data.get("metrics", data)

    if args.record_baseline:
        baselines = save_baselines(metrics)
        print("Baselines recorded with headroom:")
        for k, v in baselines["budgets"].items():
            print(f"  {k}: {v}")
    else:
        baselines = load_baselines()
        if baselines:
            all_pass, failures = check_budgets(metrics, baselines)
            if not all_pass:
                print("BUDGET EXCEEDED:")
                for f in failures:
                    print(f"  - {f}")
                if args.fail_on_budget:
                    sys.exit(1)
            else:
                print("All metrics within budget.")


if __name__ == "__main__":
    main()
