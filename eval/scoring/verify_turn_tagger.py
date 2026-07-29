#!/usr/bin/env python3
"""Verify the turn tagger by comparing inferred tags against simulator tags.

Strips the simulator's pre-existing tags from conversations, runs the
turn tagger on the raw text, then compares inferred tags vs originals.

Usage:
    uv run python eval/scoring/verify_turn_tagger.py \
        -i eval/runs/.../v0_traffic.json \
        [-n 10]  # limit to N conversations
"""

import argparse
import asyncio
import copy
import json
import logging
import os
import sys

import google.auth
from dotenv import load_dotenv

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)

env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path, override=False)

_, project_id = google.auth.default()
os.environ["GOOGLE_CLOUD_PROJECT"] = os.getenv("PROJECT_ID", project_id)
os.environ["GOOGLE_CLOUD_LOCATION"] = (
    os.getenv("MODEL_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "global"
)  # model endpoint, not infra region: gemini-3.x is global-only
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

from ensure_sdk import import_sdk_module  # noqa: E402

_sdk = import_sdk_module("quality_report")

logger = logging.getLogger(__name__)

EVAL_MODEL = os.getenv("EVAL_MODEL_ID", "gemini-2.5-flash")


def strip_tags(conv: dict) -> tuple[dict, dict]:
    """Remove simulator tags from a conversation, returning (stripped, original_tags).

    original_tags maps turn_index -> tag for user turns that had tags.
    """
    stripped = copy.deepcopy(conv)
    original_tags = {}
    turns = stripped.get("conversation", [])
    if isinstance(turns, list):
        for i, turn in enumerate(turns):
            if turn.get("role") == "user" and turn.get("tag"):
                original_tags[i] = turn["tag"]
                del turn["tag"]
    stripped["corrections"] = 0
    stripped["verifications"] = 0
    return stripped, original_tags


def print_comparison(conv: dict, original_tags: dict, tag_result: dict | None):
    """Print a side-by-side comparison of original vs inferred tags."""
    q = conv.get("question", "")[:70]
    print(f"\n{'─' * 74}")
    print(f"  Q: {q}")
    print(f"{'─' * 74}")

    turns = conv.get("conversation", [])
    if not isinstance(turns, list):
        print("  (no conversation turns)")
        return

    inferred_map = {}
    if tag_result:
        for t in tag_result.get("turn_tags", []):
            inferred_map[t["turn_index"]] = (t["tag"], t.get("evidence", ""))

    for i, turn in enumerate(turns):
        role = turn.get("role", "?")
        text = turn.get("text", "")[:100]
        if role == "user":
            orig = original_tags.get(i, "-")
            inf_tag, inf_evidence = inferred_map.get(i, ("-", ""))
            match = "OK" if orig == inf_tag else "MISMATCH"
            marker = "  " if match == "OK" else ">>"
            print(f"  {marker} [{i}] USER: {text}")
            print(f"       original={orig:<12s}  inferred={inf_tag:<12s}  [{match}]")
            if inf_evidence and match == "MISMATCH":
                print(f"       evidence: {inf_evidence[:80]}")
        else:
            print(f"     [{i}] AGENT: {text}")

    if tag_result:
        boundaries = tag_result.get("correction_boundaries", [])
        sub_trajs = tag_result.get("sub_trajectories", [])
        if boundaries:
            print(f"\n  Correction Boundaries:")
            for b in boundaries:
                print(f"    turn {b['turn_index']}: wrong='{b['wrong_claim'][:60]}'")
                print(f"              right='{b['correct_fact'][:60]}'")
                print(f"              recovered={b['agent_recovered']}")
        if sub_trajs:
            print(f"\n  Sub-Trajectories:")
            for st in sub_trajs:
                print(f"    {st['label']}: turns {st['start_turn']}-{st['end_turn']} -> {st['outcome']}")


async def run_verification(input_path: str, n: int | None, concurrency: int):
    with open(input_path) as f:
        data = json.load(f)

    conversations = data.get("conversations", [])
    multi_turn = [c for c in conversations
                  if isinstance(c.get("conversation"), list) and len(c["conversation"]) >= 3]

    if n:
        multi_turn = multi_turn[:n]

    logger.info("Verifying turn tagger on %d multi-turn conversations", len(multi_turn))

    sem = asyncio.Semaphore(concurrency)

    stripped_convs = []
    original_tags_list = []
    for conv in multi_turn:
        stripped, orig_tags = strip_tags(conv)
        stripped_convs.append(stripped)
        original_tags_list.append(orig_tags)

    async def _tag_one(conv):
        async with sem:
            turns = conv.get("conversation", [])
            return await asyncio.to_thread(
                _sdk._tag_conversation_turns, turns, EVAL_MODEL, "",
            )

    tag_results = await asyncio.gather(*[_tag_one(sc) for sc in stripped_convs])

    total_user_turns = 0
    correct_tags = 0
    total_corrections_orig = 0
    total_corrections_inferred = 0

    for conv, orig_tags, tag_result in zip(multi_turn, original_tags_list, tag_results):
        print_comparison(conv, orig_tags, tag_result)

        if tag_result:
            inferred_map = {t["turn_index"]: t["tag"] for t in tag_result.get("turn_tags", [])}
            for idx, orig_tag in orig_tags.items():
                total_user_turns += 1
                inf_tag = inferred_map.get(idx, "-")
                if orig_tag == inf_tag:
                    correct_tags += 1
            total_corrections_orig += sum(1 for t in orig_tags.values() if t == "CORRECTION")
            total_corrections_inferred += sum(
                1 for t in tag_result.get("turn_tags", []) if t["tag"] == "CORRECTION"
            )

    print(f"\n{'=' * 74}")
    print(f"  TURN TAGGER VERIFICATION SUMMARY")
    print(f"{'=' * 74}")
    print(f"  Conversations tested:   {len(multi_turn)}")
    print(f"  User turns compared:    {total_user_turns}")
    if total_user_turns > 0:
        acc = round(correct_tags / total_user_turns * 100, 1)
        print(f"  Tag accuracy:           {correct_tags}/{total_user_turns} ({acc}%)")
    print(f"  Original CORRECTIONs:   {total_corrections_orig}")
    print(f"  Inferred CORRECTIONs:   {total_corrections_inferred}")
    print(f"{'=' * 74}")


def main():
    parser = argparse.ArgumentParser(description="Verify turn tagger against simulator tags")
    parser.add_argument("--input", "-i", required=True, help="Path to traffic results JSON")
    parser.add_argument("-n", type=int, default=None, help="Limit to N conversations")
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    asyncio.run(run_verification(args.input, args.n, args.concurrency))


if __name__ == "__main__":
    main()
