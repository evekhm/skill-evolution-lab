#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Deterministically split a question set into evolve / test subsets.

Implements the held-out split from Trace2Skill (arXiv:2603.25158 §2.1): skill
evolution must use a disjoint D_evolve and D_test so that improvement is measured
on questions the patches were NOT derived from (guards against overfitting).

The split is:
  - stratified by the `category` field (each category split in the same ratio),
  - deterministic (fixed seed, sorted by id), so re-runs are reproducible
    without relying on Math.random / wall-clock.

Usage:
  python split_questions.py INPUT.json --evolve-frac 0.6 \
      --out-evolve OUT.evolve.json --out-test OUT.test.json
"""

import argparse
import hashlib
import json
from collections import defaultdict


def _stable_key(case: dict, idx: int) -> str:
    """Deterministic per-case sort key (id if present, else index)."""
    return str(case.get("id", idx))


def split_cases(cases: list[dict], evolve_frac: float, seed: int = 41):
    """Return (evolve_cases, test_cases), stratified by category, deterministic.

    Within each category, cases are ordered by a salted hash of their stable
    key so the assignment is pseudo-random but fully reproducible, then the
    first `evolve_frac` go to evolve and the rest to test.
    """
    by_cat: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for idx, case in enumerate(cases):
        key = _stable_key(case, idx)
        by_cat[case.get("category", "uncategorized")].append((key, case))

    evolve, test = [], []
    for cat in sorted(by_cat):
        items = by_cat[cat]
        # Deterministic shuffle: sort by salted hash of the stable key.
        items.sort(
            key=lambda kc: hashlib.md5(
                f"{seed}:{kc[0]}".encode()
            ).hexdigest()
        )
        n_evolve = round(len(items) * evolve_frac)
        # Guarantee at least one in each split when the category has >= 2.
        if len(items) >= 2:
            n_evolve = min(max(n_evolve, 1), len(items) - 1)
        evolve.extend(c for _, c in items[:n_evolve])
        test.extend(c for _, c in items[n_evolve:])
    return evolve, test


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input")
    ap.add_argument("--evolve-frac", type=float, default=0.6)
    ap.add_argument("--seed", type=int, default=41)
    ap.add_argument("--out-evolve", required=True)
    ap.add_argument("--out-test", required=True)
    args = ap.parse_args()

    with open(args.input) as f:
        data = json.load(f)
    cases = data["eval_cases"]

    evolve, test = split_cases(cases, args.evolve_frac, args.seed)

    base_name = data.get("name", "questions")
    for subset, path, suffix in (
        (evolve, args.out_evolve, "evolve"),
        (test, args.out_test, "test"),
    ):
        out = dict(data)
        out["name"] = f"{base_name}_{suffix}"
        out["eval_set_id"] = f"{data.get('eval_set_id', base_name)}_{suffix}"
        out["eval_cases"] = subset
        with open(path, "w") as f:
            json.dump(out, f, indent=2)

    print(
        f"Split {len(cases)} cases -> evolve={len(evolve)} ({args.out_evolve}), "
        f"test={len(test)} ({args.out_test}) "
        f"[stratified by category, seed={args.seed}]"
    )


if __name__ == "__main__":
    main()
