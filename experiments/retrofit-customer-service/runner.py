"""Drive the unmodified adk-samples customer-service agent through
scripted multi-turn conversations, with the BigQuery Agent Analytics
plugin logging every hop.

The agent under test is imported as-is from the sparse clone; this
harness adds observability around it and nothing else. Questions files
use: {"id", "category", "turns": [..], "note"} — expected answers live
in the eval spec, matched semantically by the SDK judge.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("cs-harness")
logger.setLevel(logging.INFO)

PROJECT_ID = os.environ["PROJECT_ID"]
DATASET_ID = os.environ.get("DATASET_ID", "cs_retrofit")
TABLE_ID = os.environ.get("TABLE_ID", "agent_events")
DATASET_LOCATION = os.environ.get("DATASET_LOCATION", "us-central1")


def build_plugin(labels: dict):
    from google.adk.plugins.bigquery_agent_analytics_plugin import (
        BigQueryAgentAnalyticsPlugin,
        BigQueryLoggerConfig,
    )

    config = BigQueryLoggerConfig(
        enabled=True,
        max_content_length=500 * 1024,
        batch_size=1,
        shutdown_timeout=10.0,
        custom_tags=labels,
    )
    return BigQueryAgentAnalyticsPlugin(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        table_id=TABLE_ID,
        config=config,
        location=DATASET_LOCATION,
    )


async def _send(runner, user_id, session_id, text):
    from google.genai import types

    content = types.Content(role="user", parts=[types.Part(text=text)])
    reply_parts = []
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=content
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    reply_parts.append(part.text)
    return "".join(reply_parts).strip()


async def run_conversations(questions, app_name, labels, concurrency,
                            instruction_file=None):
    from customer_service.agent import root_agent
    from google.adk.apps import App
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    if instruction_file:
        with open(instruction_file) as f:
            root_agent.instruction = f.read()
        logger.info("instruction overridden from %s", instruction_file)

    plugin = build_plugin(labels)
    app = App(root_agent=root_agent, name=app_name, plugins=[plugin])
    session_service = InMemorySessionService()
    runner = Runner(
        app=app, session_service=session_service, auto_create_session=True
    )

    sem = asyncio.Semaphore(concurrency)
    results = []

    async def one(q):
        async with sem:
            user_id = f"cs-user-{q['id']}"
            session_id = f"cs-{q['id']}-{int(time.time())}"
            transcript = []
            t0 = time.time()
            for turn in q["turns"]:
                try:
                    reply = await _send(runner, user_id, session_id, turn)
                except Exception as e:  # noqa: BLE001
                    reply = f"ERROR: {type(e).__name__}: {e}"
                transcript.append({"user": turn, "agent": reply})
                logger.info("[%s] user: %.60s", q["id"], turn)
                logger.info("[%s] agent: %.80s", q["id"], reply)
            results.append(
                {
                    "id": q["id"],
                    "category": q.get("category", "single"),
                    "session_id": session_id,
                    "turns": transcript,
                    "elapsed_s": round(time.time() - t0, 1),
                }
            )

    await asyncio.gather(*(one(q) for q in questions))
    # Flush the plugin's batch writer before process exit (review R1-5:
    # a fixed sleep raced the writer on slow runs).
    await plugin.close()
    return results


def count_logged_sessions(session_ids):
    """How many of the run's sessions have at least one BigQuery row
    (review R1-5: a clean exit must mean the rows actually landed)."""
    from google.cloud import bigquery

    client = bigquery.Client(project=PROJECT_ID)
    job = client.query(
        f"SELECT COUNT(DISTINCT session_id) AS n "
        f"FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` "
        f"WHERE session_id IN UNNEST(@ids)",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("ids", "STRING", session_ids)
            ]
        ),
        location=DATASET_LOCATION,
    )
    return next(iter(job.result())).n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", required=True)
    parser.add_argument("-o", "--out", required=True)
    parser.add_argument("--app-name", default="cymbal-cs-baseline")
    parser.add_argument("--label", default="experiment=cs_baseline_v0")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--instruction-file", default=None,
                        help="Override the agent's instruction (evolved skill)")
    parser.add_argument("--agent-version", default="cs-baseline-v0")
    args = parser.parse_args()

    # An evolved-skill run that keeps the V0 defaults would log to BigQuery
    # under baseline provenance (review R3-2 on PR #107) — refuse to start.
    # --app-name is deliberately NOT guarded: every archived run holds it
    # constant (provenance lives in agent_version/label), and changing it
    # is what produced the 0-session report (review R5-1).
    if args.instruction_file:
        stale = [
            f"--{name.replace('_', '-')}"
            for name in ("agent_version", "label")
            if getattr(args, name) == parser.get_default(name)
        ]
        if stale:
            sys.exit(
                "--instruction-file overrides the skill, but "
                + ", ".join(stale)
                + " still carry the V0 baseline default(s); pass explicit "
                "values so the run's BigQuery rows carry the right version."
            )

    with open(args.questions) as f:
        questions = json.load(f)["questions"]
    if args.limit:
        questions = questions[: args.limit]

    labels = {"agent_version": args.agent_version}
    for pair in args.label.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            labels[k.strip()] = v.strip()

    results = asyncio.run(
        run_conversations(questions, args.app_name, labels, args.concurrency,
                          instruction_file=args.instruction_file)
    )
    with open(args.out, "w") as f:
        json.dump({"app_name": args.app_name, "labels": labels,
                   "results": results}, f, indent=2)
    errors = sum(
        1 for r in results for t in r["turns"] if t["agent"].startswith("ERROR:")
    )
    logged = count_logged_sessions([r["session_id"] for r in results])
    print(f"conversations={len(results)} error_turns={errors} "
          f"bq_sessions_logged={logged}/{len(results)} out={args.out}")
    if errors or logged != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
