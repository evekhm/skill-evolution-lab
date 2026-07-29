#!/usr/bin/env python3
"""Extract a ground truth document from golden Q&A eval pairs using an LLM.

Reads golden_evals.json (curated question-answer pairs) and sends them to
Gemini to consolidate into a compact ground truth string suitable for the
``ground_truth`` field in agent_context.json.

Usage:
    # Preview to stdout
    python eval/scoring/extract_ground_truth.py \
        --input eval/data/golden_evals.json

    # Write into agent_context.json
    python eval/scoring/extract_ground_truth.py \
        --input eval/data/golden_evals.json \
        --update-config eval/data/agent_context.json
"""

import argparse
import json
import logging
import os
import shutil
import sys

import google.auth
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)

env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path, override=False)

_, project_id = google.auth.default()
PROJECT_ID = os.getenv("PROJECT_ID", project_id)
REGION = os.getenv("REGION", "us-central1")

os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = (
    os.getenv("MODEL_LOCATION") or os.getenv("GOOGLE_CLOUD_LOCATION") or "global"
)  # model endpoint, not infra region: gemini-3.x is global-only
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

EXTRACTION_PROMPT = """\
You are a ground truth extractor. Given the Q&A pairs below, extract every
verifiable factual claim into a concise reference document.

Rules:
- Group claims by topic (PTO, SICK LEAVE, REMOTE WORK, EXPENSES, etc.)
- Include ONLY verifiable facts: numbers, dates, limits, percentages, yes/no
- Use the compact format: TOPIC: claim1, claim2, claim3.
- For out-of-scope topics, list them under OUT OF SCOPE
- Do NOT add any facts not present in the Q&A pairs
- Do NOT include prose, explanations, or commentary
- Keep the total output under 1500 characters

Example output format:
PTO: 20 days/year, accrued monthly (~1.67/mo), max 5 rollover. SICK LEAVE: 10 days/year, NO rollover.

Q&A PAIRS:
{qa_pairs}
"""


def load_golden_evals(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return data.get("eval_cases", data.get("questions", []))


def format_qa_pairs(evals: list[dict]) -> str:
    parts = []
    for e in evals:
        q = e.get("question", "")
        a = e.get("expected_answer", "")
        topic = e.get("topic", "")
        tag = f" [{topic}]" if topic else ""
        parts.append(f"Q{tag}: {q}\nA: {a}")
    return "\n\n".join(parts)


def extract_ground_truth(golden_evals_path: str, model: str | None = None) -> str:
    from google import genai
    from google.genai import types

    model = model or os.getenv("EVAL_MODEL_ID", "gemini-2.5-flash")
    evals = load_golden_evals(golden_evals_path)
    qa_text = format_qa_pairs(evals)
    prompt = EXTRACTION_PROMPT.format(qa_pairs=qa_text)

    client = genai.Client()
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.0),
    )
    return response.text.strip()


def update_config(config_path: str, ground_truth: str) -> None:
    backup_path = config_path + ".bak"
    shutil.copy2(config_path, backup_path)
    logger.info("Backup saved to %s", backup_path)

    with open(config_path) as f:
        config = json.load(f)

    config["ground_truth"] = ground_truth

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    logger.info("Updated ground_truth in %s", config_path)


def main():
    parser = argparse.ArgumentParser(
        description="Extract ground truth from golden Q&A eval pairs"
    )
    parser.add_argument(
        "--input", "-i", required=True,
        help="Path to golden_evals.json",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Gemini model (default: EVAL_MODEL_ID or gemini-2.5-flash)",
    )
    parser.add_argument(
        "--update-config", type=str, default=None, metavar="PATH",
        help="Write ground_truth into this agent_context.json (backup created)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    logger.info("Extracting ground truth from %s", args.input)
    ground_truth = extract_ground_truth(args.input, model=args.model)

    if args.update_config:
        update_config(args.update_config, ground_truth)
        print(f"Updated {args.update_config}")
        print(f"\nGenerated ground truth ({len(ground_truth)} chars):")
    else:
        print(f"Generated ground truth ({len(ground_truth)} chars):")

    print(ground_truth)


if __name__ == "__main__":
    main()
