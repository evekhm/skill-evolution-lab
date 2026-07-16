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

"""Tools for the Quality Agent.

Provides two tools:
- run_quality_report: delegates to quality_report.py for evaluation
- create_github_issue: creates an issue on GitHub for HITL review

GitHub issue creation supports two backends (tried in order):
  1. ``gh`` CLI — authenticated via GH_TOKEN env var (set via Secret
     Manager ``--set-secrets`` in Cloud Run, or ``gh auth login`` locally).
  2. PyGithub fallback — uses a GitHub App (private key + config from
     Secret Manager secrets ``github-app-key`` and ``github-app-config``)
     to generate short-lived installation tokens.

Rich issue bodies are optionally generated via ``agy`` when available.
"""

import concurrent.futures
import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone

import google.auth

logger = logging.getLogger(__name__)

_script_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_script_dir, "../../.."))

# ---------------------------------------------------------------------------
# Dry-run mode: write markdown files instead of creating GitHub issues/PRs
# ---------------------------------------------------------------------------

_DRY_RUN = False
_DRY_RUN_DIR = os.path.join(_repo_root, "eval", "runs", "dry_run_output")


def enable_dry_run(output_dir: str | None = None):
    """Enable dry-run mode: tools write local markdown instead of GitHub."""
    global _DRY_RUN, _DRY_RUN_DIR
    _DRY_RUN = True
    if output_dir:
        _DRY_RUN_DIR = output_dir


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_, _project_id = google.auth.default()
PROJECT_ID = os.getenv("PROJECT_ID", _project_id or "")
DATASET_ID = os.getenv("DATASET_ID", "agent_logs")
DATASET_LOCATION = os.getenv("DATASET_LOCATION", "us-central1")
TABLE_ID = os.getenv("TABLE_ID", "agent_events")


# ---------------------------------------------------------------------------
# Agent registry (replaces hardcoded _AGENT_FILES)
# ---------------------------------------------------------------------------

_DEFAULT_REGISTRY_PATHS = [
    os.path.join(_repo_root, "eval", "skill_evolution", "agent_registry.json"),
    os.path.join(_repo_root, "agent_registry.json"),
]


def _load_agent_registry(path: str | None = None) -> dict:
    if path is None:
        path = os.environ.get("AGENT_REGISTRY")
    if path is None:
        for candidate in _DEFAULT_REGISTRY_PATHS:
            if os.path.isfile(candidate):
                path = candidate
                break
    if not path or not os.path.isfile(path):
        logger.warning("No agent_registry.json found. Set AGENT_REGISTRY env var.")
        return {"agents": {}}
    with open(path) as f:
        return json.load(f)


_REGISTRY = _load_agent_registry()


# ---------------------------------------------------------------------------
# Quality config (severity thresholds)
# ---------------------------------------------------------------------------

def _load_quality_config() -> dict:
    for base in [_repo_root, _script_dir]:
        path = os.path.join(base, "eval", "data", "quality_config.json")
        if os.path.isfile(path):
            with open(path) as f:
                return json.load(f)
    return {"thresholds": {"urgent_below": 80, "warning_below": 95}}


_QUALITY_CONFIG = _load_quality_config()
URGENT_BELOW = float(
    os.getenv("QUALITY_URGENT_BELOW", _QUALITY_CONFIG["thresholds"]["urgent_below"])
)
WARNING_BELOW = float(
    os.getenv("QUALITY_WARNING_BELOW", _QUALITY_CONFIG["thresholds"]["warning_below"])
)


def _get_agent_files(agent_name: str) -> list[str]:
    """Resolve agent name to file paths using the registry."""
    agents = _REGISTRY.get("agents", {})
    if agent_name in agents:
        skill_dir = agents[agent_name]["skill_dir"]
        agent_dir = os.path.dirname(skill_dir)
        return [f"{agent_dir}/prompts.py", f"{agent_dir}/tools.py"]
    return [f"agents/{agent_name}/"]


# ---------------------------------------------------------------------------
# Helpers: agy + gh CLI
# ---------------------------------------------------------------------------


def _find_agy() -> str | None:
    """Find the agy CLI binary."""
    path = shutil.which("agy")
    if path:
        return path
    for c in [os.path.expanduser("~/.local/bin/agy"), "/usr/local/bin/agy"]:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _gh_available() -> bool:
    """Check if gh CLI is available and authenticated."""
    try:
        r = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True, text=True,
        )
        return r.returncode == 0
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Fallback: PyGithub auth via GitHub App (Secret Manager)
# ---------------------------------------------------------------------------

_sm_client = None


def _get_sm_client():
    global _sm_client
    if _sm_client is None:
        from google.cloud import secretmanager
        _sm_client = secretmanager.SecretManagerServiceClient()
    return _sm_client


def _read_secret(name: str) -> str:
    """Read a secret from Secret Manager."""
    return (
        _get_sm_client()
        .access_secret_version(
            request={"name": f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"}
        )
        .payload.data.decode("utf-8")
    )


def _get_app_config() -> dict:
    """Read GitHub App config (app_id, installation_id, repo) from Secret Manager."""
    return json.loads(_read_secret("github-app-config"))


def _get_github_token() -> str:
    """Generate a short-lived GitHub App installation token."""
    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if env_token:
        return env_token

    import jwt
    import requests

    config = _get_app_config()
    key_pem = _read_secret("github-app-key")

    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": str(config["app_id"])}
    token = jwt.encode(payload, key_pem, algorithm="RS256")

    resp = requests.post(
        f"https://api.github.com/app/installations/{config['installation_id']}/access_tokens",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    resp.raise_for_status()
    return resp.json()["token"]


def _get_github_repo():
    """Return a PyGithub Repository object."""
    from github import Github

    config = _get_app_config()
    g = Github(_get_github_token())
    return g.get_repo(config["repo"])


# ---------------------------------------------------------------------------
# Tool: run_quality_report
# ---------------------------------------------------------------------------


def _trim_session(s: dict) -> dict:
    """Return a lightweight session summary for the LLM.

    Full session data (conversation traces, metrics, quality_scores) is
    stripped to keep LLM context small. The full data is available on
    disk via report_path and loaded by create_github_issue.
    """
    metrics = s.get("metrics", {})
    usefulness = metrics.get("response_usefulness", {})
    grounding = metrics.get("task_grounding", {})
    return {
        "session_id": s.get("session_id", ""),
        "question": (s.get("question", "") or "").split(" | For context:")[0].strip(),
        "verdict": usefulness.get("category", "unknown"),
        "grounding": grounding.get("category", "unknown"),
        "agent": s.get("answered_by", "unknown"),
        "user_turns": s.get("user_turns", 0),
        "tool_calls": s.get("tool_calls", 0),
        "reason": (usefulness.get("justification", "") or "")[:200],
    }


def _load_full_sessions(report_path: str) -> dict[str, dict]:
    """Load full session data from the saved quality report, keyed by session_id."""
    if not report_path or not os.path.isfile(report_path):
        return {}
    with open(report_path) as f:
        report = json.load(f)
    return {
        s.get("session_id", ""): s
        for s in report.get("sessions", [])
        if s.get("session_id")
    }


def run_quality_report(
    time_period: str = "6h",
    output_dir: str | None = None,
    agent_version: str | None = None,
) -> dict:
    """Run a quality report on recent agent sessions from BigQuery.

    Uses the shared quality_report module (scripts/test/quality_report.py)
    to query sessions and score each one with an LLM judge on
    response_usefulness (meaningful / partial / unhelpful) and
    task_grounding (grounded / ungrounded).

    Returns per-agent breakdown, category distributions, and all
    session-level verdicts.

    Args:
        time_period: How far back to look. Examples: '6h', '30m', '1d', 'all'.
        output_dir: If set, save the quality report JSON to this directory.
        agent_version: If set, filter sessions to this agent version
            (matches custom_tags.agent_version in BigQuery).

    Returns:
        A dict with 'summary' (counts, rates, per_agent breakdown),
        'category_distributions', 'per_agent', 'sessions' (list of
        per-session verdicts), and 'details'.
    """
    from .quality_report import (
        _build_json_output,
        _load_config,
        run_evaluation,
    )

    try:
        # Ensure the shared module picks up our env vars
        os.environ.setdefault("PROJECT_ID", PROJECT_ID)
        os.environ.setdefault("DATASET_ID", DATASET_ID)
        os.environ.setdefault("TABLE_ID", TABLE_ID)
        os.environ.setdefault("DATASET_LOCATION", DATASET_LOCATION)
        _load_config()

        # run_evaluation uses asyncio.run() internally, which fails
        # when called from the ADK runner's event loop. Run it in a
        # separate thread so it gets its own event loop.
        custom_labels = None
        if agent_version:
            custom_labels = {"agent_version": agent_version}

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(
                run_evaluation,
                time_range=time_period,
                limit=100,
                custom_labels=custom_labels,
            ).result()
        report = result["report"]
        resolved_map = result["resolved_map"]

        if not report.session_results:
            return {
                "summary": {
                    "total_sessions": 0,
                    "message": f"No sessions found in last {time_period}",
                },
                "sessions": [],
            }

        output = _build_json_output(report, resolved_map)
        output["summary"]["time_period"] = time_period
        if agent_version:
            output["summary"]["agent_version"] = agent_version

        logger.info(
            "Quality report: %d sessions, %.1f%% meaningful, %.1f%% unhelpful",
            output["summary"]["total_sessions"],
            output["summary"]["meaningful_rate"],
            output["summary"]["unhelpful_rate"],
        )

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            report_path = os.path.join(output_dir, "quality_report.json")
            with open(report_path, "w") as f:
                json.dump(output, f, indent=2, default=str)
            output["report_path"] = report_path
            logger.info("Quality report saved to %s", report_path)

        # Trim sessions returned to the LLM to reduce context bloat.
        # Full session data stays on disk (report_path) and is loaded
        # by create_github_issue when building the issue body.
        if output.get("sessions"):
            output["sessions"] = [
                _trim_session(s) for s in output["sessions"]
            ]

        return output

    except Exception as e:
        logger.error(f"Quality report failed: {e}")
        return {
            "summary": {"total_sessions": 0, "error": str(e)},
            "sessions": [],
        }


# ---------------------------------------------------------------------------
# Tool: upload_quality_report
# ---------------------------------------------------------------------------


def upload_quality_report(run_dir: str) -> dict:
    """Upload a quality report run directory to GCS.

    Uploads all files in the run directory (quality_report.json, etc.)
    to GCS for archival and consumption by the evolution agent.

    Controlled by GCS_UPLOAD env var (default: false). GCS_BUCKET must
    be configured in .env.

    Args:
        run_dir: Local path to the quality report run directory.

    Returns:
        Dict with status, gcs_uri, and files_uploaded count.
    """
    from agents.workflow.gcs_utils import upload_dir_to_gcs

    return upload_dir_to_gcs(
        run_dir, prefix="quality-reports",
    )


# ---------------------------------------------------------------------------
# Tool: create_github_issue
# ---------------------------------------------------------------------------


def _build_issue_body(
    category: str,
    agent_name: str,
    topic: str,
    severity: str,
    root_cause: str,
    failure_patterns: list[dict],
    recommendation: str,
    affected_sessions: list[dict],
    summary: dict,
    report_uri: str = "",
    agent_version: str = "",
) -> str:
    """Build the structured issue body markdown."""
    meaningful_rate = summary.get("meaningful_rate", 100)
    n = len(affected_sessions)

    action_map = {
        "prompt-gap": "prompt-fix",
        "hallucination": "prompt-fix",
        "routing": "routing-fix",
        "tool-error": "tool-fix",
    }
    action_type = action_map.get(category, "investigation")
    files = _get_agent_files(agent_name)

    parts = []

    # 1. Metadata table
    parts.append("## Metadata\n")
    parts.append("| Field | Value |")
    parts.append("|-------|-------|")
    parts.append(f"| Category | `{category}` |")
    parts.append(f"| Topic | {topic} |")
    parts.append(f"| Severity | `{severity}` |")
    parts.append(f"| Agent | `{agent_name}` |")
    parts.append(f"| Action needed | `{action_type}` |")
    parts.append(f"| Sessions affected | {n} |")
    parts.append(f"| Meaningful rate | {meaningful_rate}% |")
    parts.append(f"| Time period | `{summary.get('time_period', '?')}` |")
    parts.append(f"| Files to investigate | {', '.join(f'`{f}`' for f in files)} |")
    if agent_version:
        parts.append(f"| Agent version | `{agent_version}` |")
    if report_uri:
        parts.append(f"| Quality report | `{report_uri}` |")

    # 2. Root cause
    parts.append("\n## Root Cause\n")
    parts.append(root_cause)

    # 3. Failure patterns table
    if failure_patterns:
        parts.append("\n## Failure Patterns\n")
        parts.append("| Pattern | Count | Verdict | Example |")
        parts.append("|---------|-------|---------|---------|")
        for fp in failure_patterns:
            parts.append(
                f"| {fp.get('pattern', '')} "
                f"| {fp.get('count', '?')} "
                f"| {fp.get('verdict', '?')} "
                f"| {fp.get('example_question', '')[:80]} |"
            )

    # 4. Recommended fix
    parts.append("\n## Recommended Fix\n")
    parts.append(recommendation)

    # 5. Reproduce commands (deduplicated questions)
    seen_questions = set()
    reproduce_questions = []
    for s in affected_sessions:
        q = s.get("question", "")
        clean_q = q.split(" | For context:")[0].strip()
        if clean_q and clean_q not in seen_questions:
            seen_questions.add(clean_q)
            reproduce_questions.append(clean_q)
    if reproduce_questions:
        parts.append("\n## Reproduce\n")
        parts.append("```bash")
        parts.append("# Run these queries to verify the failures:")
        for q in reproduce_questions:
            escaped = q.replace('"', '\\"')
            parts.append(f'bash scripts/test/smoke_test_deployed.sh "{escaped}"')
        parts.append("```")

    # 6. Quality report summary
    parts.append("\n---\n## Quality Report Summary\n")
    parts.append("| Metric | Value |")
    parts.append("|--------|-------|")
    parts.append(f"| Time period | `{summary.get('time_period', '?')}` |")
    parts.append(f"| Total sessions | {summary.get('total_sessions', 0)} |")
    parts.append(
        f"| Meaningful | {summary.get('meaningful', 0)} ({meaningful_rate}%) |"
    )
    declined = summary.get("declined", 0)
    if declined:
        parts.append(f"| Declined (out-of-scope) | {declined} |")
    parts.append(f"| Partial | {summary.get('partial', 0)} |")
    parts.append(
        f"| Unhelpful | {summary.get('unhelpful', 0)} ({summary.get('unhelpful_rate', 0)}%) |"
    )

    dim_avgs = summary.get("dimension_averages", {})
    if dim_avgs:
        parts.append("\n**Quality Dimensions** (0–2 scale):\n")
        parts.append("| Dimension | Score |")
        parts.append("|-----------|-------|")
        for dim, score in dim_avgs.items():
            parts.append(f"| {dim} | {score} / 2.00 |")

    parts.append(
        f"\n**Dataset:** `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}` (location: `{DATASET_LOCATION}`)"
    )

    # 7. Affected sessions with full traces (collapsible)
    if affected_sessions:
        parts.append(f"\n---\n<details>\n<summary>Affected Sessions ({n})</summary>\n")
        for i, s in enumerate(affected_sessions, 1):
            sid = s.get("session_id", "unknown")
            metrics = s.get("metrics", {})
            usefulness = metrics.get("response_usefulness", {})
            grounding = metrics.get("task_grounding", {})
            quality_scores = s.get("quality_scores", {})
            question = s.get("question", "").split(" | For context:")[0].strip()

            parts.append(f"### Session {i}: `{sid}`\n")
            parts.append(
                f"- **Agent:** `{s.get('answered_by', '?')}` "
                f"| **Latency:** {s.get('latency_s', '?')}s "
                f"| **Turns:** {s.get('user_turns', 0)} "
                f"| **Tool calls:** {s.get('tool_calls', 0)}"
            )
            parts.append(
                f"- **Verdict:** {usefulness.get('category', '?')} / "
                f"{grounding.get('category', '?')}"
            )
            if quality_scores:
                scores_str = " | ".join(
                    f"{d}: {v.get('score', '?')}/2"
                    for d, v in quality_scores.items()
                )
                parts.append(f"- **Scores:** {scores_str}")
            parts.append(f"- **Question:** {question}")
            parts.append(f"- **Response:** {s.get('response', '')[:500]}")
            parts.append(
                f"- **Usefulness reason:** {usefulness.get('justification', '')}"
            )

            conversation = s.get("conversation", [])
            if conversation and len(conversation) > 2:
                parts.append(
                    f"\n<details>\n<summary>Full conversation trace "
                    f"({len(conversation)} turns)</summary>\n"
                )
                for turn in conversation:
                    role = turn.get("role", "?").upper()
                    text = turn.get("text", "")[:1000]
                    tag = turn.get("inferred_tag", "")
                    tag_label = f" `[{tag}]`" if tag else ""
                    parts.append(f"**{role}**{tag_label}: {text}\n")
                parts.append("</details>")

            parts.append("")
        parts.append("</details>")

    # 7b. Machine-extractable session IDs (outside collapsible block)
    if affected_sessions:
        parts.append(f"\n## Session IDs ({n})\n")
        parts.append("```text")
        for s in affected_sessions:
            parts.append(s.get("session_id", "unknown"))
        parts.append("```")

    # 8. Footer
    parts.append(
        "\n---\n*Created by "
        "Quality Agent "
        f"| Dataset: `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`*"
    )

    return "\n".join(parts)


def create_github_issue(
    category: str,
    agent_name: str,
    topic: str,
    root_cause: str,
    failure_patterns: list[dict],
    recommendation: str,
    affected_sessions: list[dict],
    summary: dict,
    report_uri: str = "",
    report_path: str = "",
    agent_version: str = "",
) -> dict:
    """Create a structured GitHub issue for a specific quality problem.

    Each issue should represent ONE distinct problem — a specific root
    cause or topic within a failure category. For example, "missing
    sick leave data" and "missing educational expense data" are both
    prompt-gap issues but should be separate GitHub issues because they
    need different fixes.

    The issue is formatted so that both humans and the Evolution Agent can
    act on it: machine-readable metadata table at the top, root cause
    analysis, failure patterns, recommended fix, and reproduce commands.

    Uses ``gh`` CLI for GitHub API and ``agy`` for rich body generation.

    The affected_sessions can be lightweight (trimmed by run_quality_report).
    If report_path is provided, full session data is loaded from the saved
    report on disk to build the rich issue body with conversation traces.

    Args:
        category: Failure category. One of: 'routing', 'hallucination',
                  'prompt-gap', 'tool-error', 'regression', 'new-topic'.
        agent_name: The agent responsible for the failures,
                    e.g. 'policy_agent', 'hr_calculator'.
        topic: Short description of the specific problem, e.g.
                    'missing educational expense data' or
                    'sick leave coverage info not found'. This is used
                    in the issue title to distinguish different problems
                    within the same category.
        root_cause: 2-4 sentence root cause analysis explaining WHY
                    the failures happen.
        failure_patterns: List of pattern dicts, each with:
                    - pattern: short description of the failure pattern
                    - count: number of sessions matching this pattern
                    - verdict: 'unhelpful' or 'partial'
                    - example_question: one representative question
        recommendation: Concrete recommended fix. Reference specific files
                    or prompt sections when possible.
        affected_sessions: List of session dicts from the quality report.
                    Can be trimmed (session_id + verdict only) — full data
                    is loaded from report_path if available.
        summary: The quality report summary dict (total_sessions,
                 meaningful_rate, unhelpful_rate, time_period, etc.).
        report_uri: GCS URI or local path to the quality report.
                    Included in the issue metadata so the evolution
                    agent can find the full report data.
        report_path: Local path to the saved quality_report.json.
                    Used to load full session data for the issue body.
        agent_version: Software version of the agent being evaluated.
                    Added as a label (``version:{agent_version}``) for
                    filtering and as a metadata row in the issue body.

    Returns:
        A dict with 'status', 'url', and 'number' of the created issue,
        or 'updated' if new sessions were appended to an existing issue.
    """
    # Hydrate trimmed sessions with full data from disk
    if report_path:
        full_sessions = _load_full_sessions(report_path)
        if full_sessions:
            hydrated = []
            for s in affected_sessions:
                sid = s.get("session_id", "")
                if sid in full_sessions:
                    hydrated.append(full_sessions[sid])
                else:
                    hydrated.append(s)
            affected_sessions = hydrated

    n = len(affected_sessions)

    # Urgency is driven by how many sessions hit this specific problem,
    # not by the overall meaningful_rate (which would mark every issue
    # as urgent when overall quality dips).
    urgent_session_threshold = int(os.getenv("QUALITY_URGENT_SESSION_COUNT", "5"))
    if n >= urgent_session_threshold or category == "regression":
        severity = "urgent"
    elif n >= 2:
        severity = "warning"
    else:
        severity = "info"

    title = f"[Quality] {category}: {topic} — {agent_name}"
    if severity == "urgent":
        title = f"[Quality][URGENT] {category}: {topic} — {agent_name}"

    labels = ["quality", category]
    if agent_version:
        labels.append(f"version:{agent_version}")

    issue_body = _build_issue_body(
        category, agent_name, topic, severity, root_cause,
        failure_patterns, recommendation, affected_sessions, summary,
        report_uri=report_uri,
        agent_version=agent_version,
    )

    # Try agy for richer body
    agy_bin = _find_agy()
    if agy_bin:
        agy_prompt = (
            f"Rewrite the following GitHub issue body to be more readable "
            f"and actionable. Keep all data, tables, and collapsible sections "
            f"intact. Improve the prose in Root Cause and Recommended Fix "
            f"sections. Output ONLY the issue body markdown.\n\n"
            f"---\n{issue_body}"
        )
        try:
            r = subprocess.run(
                [agy_bin, "-p", agy_prompt],
                cwd=_repo_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if r.returncode == 0 and r.stdout.strip():
                issue_body = r.stdout.strip()
        except Exception as e:
            logger.warning("agy issue generation failed: %s", e)

    # Dry-run: write to local file instead of GitHub
    if _DRY_RUN:
        os.makedirs(_DRY_RUN_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_cat = category.replace("/", "-")
        safe_agent = agent_name.replace("/", "-")
        safe_topic = topic.replace("/", "-").replace(" ", "_")[:40]
        filename = f"issue_{safe_cat}_{safe_topic}_{safe_agent}_{ts}.md"
        filepath = os.path.join(_DRY_RUN_DIR, filename)
        with open(filepath, "w") as f:
            f.write(f"# {title}\n\n")
            f.write(f"**Labels:** {', '.join(labels)}\n\n")
            f.write(issue_body + "\n")
        print(f"\n  [DRY RUN] Issue written to: {filepath}")
        logger.info("Dry-run: wrote issue to %s", filepath)
        return {"status": "dry_run", "file": filepath, "title": title}

    # Determine run directory for .md persistence
    run_dir = os.path.dirname(report_path) if report_path else None

    # Try gh CLI first, fall back to PyGithub
    if _gh_available():
        result = _create_issue_gh(
            title, issue_body, labels,
            category=category, agent_name=agent_name, topic=topic,
            agent_version=agent_version,
            affected_sessions=affected_sessions, summary=summary,
        )
    else:
        logger.info("gh CLI not available, falling back to PyGithub")
        result = _create_issue_pygithub(
            title, issue_body, labels,
            category=category, agent_name=agent_name, topic=topic,
            agent_version=agent_version,
            affected_sessions=affected_sessions, summary=summary,
        )

    # Save issue as .md in run directory
    if run_dir and result.get("status") in ("created", "updated"):
        issue_num = result.get("number", "unknown")
        safe_topic = topic.replace("/", "-").replace(" ", "_")[:40]
        md_path = os.path.join(
            run_dir, f"issue_{issue_num}_quality_{safe_topic}.md",
        )
        with open(md_path, "w") as f:
            f.write(f"# {title}\n\n")
            f.write(f"**Issue:** {result.get('url', 'N/A')}\n")
            f.write(f"**Labels:** {', '.join(labels)}\n\n")
            f.write(issue_body + "\n")
        result["md_path"] = md_path
        logger.info("Saved quality issue .md to %s", md_path)

    return result


def _find_existing_issue(
    category: str, agent_name: str, topic: str, agent_version: str,
) -> int | None:
    """Find an existing open issue matching this problem + version."""
    label_args = ["--label", "quality"]
    if agent_version:
        label_args.extend(["--label", f"version:{agent_version}"])

    try:
        r = subprocess.run(
            ["gh", "issue", "list", "--state", "open", *label_args,
             "--json", "number,title", "--limit", "50"],
            cwd=_repo_root, capture_output=True, text=True,
        )
        if r.returncode != 0:
            return None

        existing = json.loads(r.stdout)
        target_key = f"{category}: {topic}"
        for issue in existing:
            if target_key in issue["title"] and agent_name in issue["title"]:
                return issue["number"]
    except Exception as e:
        logger.warning("Existing issue search failed: %s", e)
    return None


def _build_update_comment(
    affected_sessions: list[dict], summary: dict,
) -> str:
    """Build a comment body for appending new sessions to an existing issue."""
    n = len(affected_sessions)
    parts = [
        f"## New Sessions Found ({n})\n",
        f"**Time period:** `{summary.get('time_period', '?')}`",
        f"**Meaningful rate:** {summary.get('meaningful_rate', '?')}%\n",
    ]

    parts.append("### Session IDs\n")
    parts.append("```text")
    for s in affected_sessions:
        parts.append(s.get("session_id", "unknown"))
    parts.append("```\n")

    parts.append(f"<details>\n<summary>Session Details ({n})</summary>\n")
    for i, s in enumerate(affected_sessions, 1):
        sid = s.get("session_id", "unknown")
        metrics = s.get("metrics", {})
        usefulness = metrics.get("response_usefulness", {})
        grounding = metrics.get("task_grounding", {})
        question = s.get("question", "").split(" | For context:")[0].strip()

        parts.append(f"### Session {i}: `{sid}`\n")
        parts.append(
            f"- **Agent:** `{s.get('answered_by', '?')}` "
            f"| **Turns:** {s.get('user_turns', 0)} "
            f"| **Tool calls:** {s.get('tool_calls', 0)}"
        )
        parts.append(
            f"- **Verdict:** {usefulness.get('category', '?')} / "
            f"{grounding.get('category', '?')}"
        )
        parts.append(f"- **Question:** {question}")
        parts.append(f"- **Response:** {s.get('response', '')[:500]}")
        parts.append("")
    parts.append("</details>")

    return "\n".join(parts)


def _update_existing_issue_gh(
    issue_number: int, affected_sessions: list[dict], summary: dict,
) -> dict:
    """Append new failing sessions to an existing open issue via comment."""
    comment_body = _build_update_comment(affected_sessions, summary)
    n = len(affected_sessions)

    try:
        r = subprocess.run(
            ["gh", "issue", "comment", str(issue_number),
             "--body", comment_body],
            cwd=_repo_root, capture_output=True, text=True,
        )
        if r.returncode != 0:
            return {"status": "error", "error": f"Comment failed: {r.stderr}"}

        logger.info(
            "Updated issue #%s with %d new sessions", issue_number, n,
        )
        return {
            "status": "updated",
            "issue_number": issue_number,
            "new_sessions": n,
        }
    except Exception as e:
        logger.error("Failed to update issue #%s: %s", issue_number, e)
        return {"status": "error", "error": str(e)}


def _create_issue_gh(
    title: str, body: str, labels: list[str],
    *,
    category: str, agent_name: str, topic: str, agent_version: str,
    affected_sessions: list[dict], summary: dict,
) -> dict:
    """Create or update issue via gh CLI."""
    existing = _find_existing_issue(category, agent_name, topic, agent_version)
    if existing:
        return _update_existing_issue_gh(existing, affected_sessions, summary)

    try:
        label_args = []
        for label in labels:
            label_args.extend(["--label", label])

        r = subprocess.run(
            ["gh", "issue", "create",
             "--title", title,
             "--body", body,
             *label_args],
            cwd=_repo_root,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            logger.warning("gh issue create failed with labels: %s", r.stderr)
            r = subprocess.run(
                ["gh", "issue", "create",
                 "--title", title,
                 "--body", body],
                cwd=_repo_root,
                capture_output=True,
                text=True,
            )
        if r.returncode != 0:
            return {"status": "error", "error": r.stderr}

        issue_url = r.stdout.strip()
        issue_number = issue_url.rstrip("/").split("/")[-1]
        logger.info("Created issue #%s: %s", issue_number, issue_url)
        return {
            "status": "created",
            "url": issue_url,
            "number": int(issue_number),
            "title": title,
        }
    except Exception as e:
        logger.error("gh issue create failed: %s", e)
        return {"status": "error", "error": str(e)}


def _create_issue_pygithub(
    title: str, body: str, labels: list[str],
    *,
    category: str, agent_name: str, topic: str, agent_version: str,
    affected_sessions: list[dict], summary: dict,
) -> dict:
    """Create or update issue via PyGithub (fallback)."""
    try:
        repo = _get_github_repo()

        # Search for existing issue to update
        label_filters = ["quality"]
        if agent_version:
            label_filters.append(f"version:{agent_version}")
        target_key = f"{category}: {topic}"
        for issue in repo.get_issues(state="open", labels=label_filters):
            if target_key in issue.title and agent_name in issue.title:
                comment_body = _build_update_comment(
                    affected_sessions, summary,
                )
                issue.create_comment(comment_body)
                logger.info(
                    "Updated issue #%s with %d new sessions",
                    issue.number, len(affected_sessions),
                )
                return {
                    "status": "updated",
                    "issue_number": issue.number,
                    "new_sessions": len(affected_sessions),
                }

        issue = repo.create_issue(title=title, body=body, labels=labels)
        logger.info(f"Created issue #{issue.number}: {title}")
        return {"status": "created", "url": issue.html_url, "number": issue.number}
    except Exception as e:
        logger.error(f"PyGithub issue creation failed: {e}")
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Tool: search_similar_sessions (BigQuery Conversational Analytics)
# ---------------------------------------------------------------------------


def search_similar_sessions(
    question: str,
    time_period: str = "30d",
    limit: int = 10,
) -> dict:
    """Search for similar past sessions using BigQuery Conversational Analytics.

    Uses the CA Data Agent to perform natural language queries over the
    agent event log table. This enables regression detection (a question
    that used to be answered correctly but now fails) and new-topic
    discovery (a question that has never been answered).

    Args:
        question: The user question to search for similar past sessions.
        time_period: How far back to search. Examples: '7d', '30d', '90d'.
        limit: Maximum number of similar sessions to return.

    Returns:
        A dict with:
        - similar_sessions: list of past sessions with question, response,
          and quality verdict
        - has_historical_answers: whether similar questions were answered
          successfully in the past
        - regression_detected: True if past sessions were meaningful but
          current ones are unhelpful
        - analysis: natural language summary from the CA agent
    """
    try:
        from google.cloud.geminidataanalytics import (
            BigQueryTableReference,
            BigQueryTableReferences,
            ChatRequest,
            Context,
            DataChatServiceClient,
            DatasourceReferences,
            Message,
            UserMessage,
        )

        full_table = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

        # Build the natural language query
        nl_query = (
            f"Find sessions from the last {time_period} where the user asked "
            f"questions similar to: '{question}'. "
            f"For each matching session, show the session_id, "
            f"the user's question (from USER_MESSAGE_RECEIVED events), "
            f"which agent responded, whether a tool was called, "
            f"and the final response text. "
            f"Limit to {limit} most recent matches."
        )

        # Use the stateless chat API with inline_context
        table_ref = BigQueryTableReference(
            project_id=PROJECT_ID,
            dataset_id=DATASET_ID,
            table_id=TABLE_ID,
        )
        context = Context(
            datasource_references=DatasourceReferences(
                bq=BigQueryTableReferences(
                    table_references=[table_ref],
                ),
            ),
        )

        # CA API uses 'us' or 'eu' as location (BQ multi-region)
        ca_location = os.getenv("CA_LOCATION", "us")
        parent = f"projects/{PROJECT_ID}/locations/{ca_location}"

        client = DataChatServiceClient()
        responses = client.chat(
            request=ChatRequest(
                parent=parent,
                inline_context=context,
                messages=[
                    Message(
                        user_message=UserMessage(text=nl_query),
                    ),
                ],
            )
        )

        # Collect text responses and data from the streaming response
        text_parts = []
        generated_sql = ""
        data_rows = []
        for msg in responses:
            sm = msg.system_message
            if not sm:
                continue
            if sm.text and sm.text.parts:
                text_parts.extend(sm.text.parts)
            if sm.data:
                if sm.data.generated_sql:
                    generated_sql = sm.data.generated_sql
                if sm.data.result and sm.data.result.data:
                    # DataResult.data is a list of Struct (protobuf)
                    for row_struct in sm.data.result.data:
                        row = dict(row_struct)
                        data_rows.append(row)

        # Convert data rows to session dicts
        similar = []
        has_answers = False
        for row in data_rows[:limit]:
            session = {k: str(v) for k, v in row.items()}
            similar.append(session)
            for v in session.values():
                if v and len(v) > 50:
                    has_answers = True

        # The final text parts usually contain the natural language answer
        analysis = text_parts[-1] if text_parts else ""

        return {
            "similar_sessions": similar,
            "has_historical_answers": has_answers,
            "regression_detected": has_answers,  # refined by quality agent
            "analysis": analysis,
            "generated_sql": generated_sql,
            "query_used": nl_query,
            "table": full_table,
        }

    except ImportError:
        logger.warning(
            "google-cloud-geminidataanalytics not installed. "
            "Install with: pip install google-cloud-geminidataanalytics"
        )
        return {
            "similar_sessions": [],
            "has_historical_answers": False,
            "regression_detected": False,
            "analysis": "CA agent not available (google-cloud-geminidataanalytics not installed)",
            "error": "missing_dependency",
        }
    except Exception as e:
        logger.error(f"CA agent search failed: {e}")
        return {
            "similar_sessions": [],
            "has_historical_answers": False,
            "regression_detected": False,
            "analysis": f"CA agent search failed: {e}",
            "error": str(e),
        }


