"""Hooks adapter: wires the SDK's generic skill-evolution Cloud Run Job
(``deploy/skill_evolution_job`` in BigQuery-Agent-Analytics-SDK) to this
lab's existing machinery.

Usage: set ``EVOLUTION_HOOKS=eval.skill_evolution_hooks``. The job
imports the module with its host-repo workdir (a clone of this repo) on
``sys.path``; for local runs export ``PYTHONPATH=<lab repo root>``.

Hook contracts implemented (see the job's ``hooks.py``):

- ``traffic(run_dir) -> dict``          -> lab traffic_generator
- ``score(candidate, skill_dir, run_dir) -> dict``  -> tools.score_candidate
- ``gate(run_dir, version, agent) -> (bool|None, str)`` -> pytest publish gate
- ``toolbox(agent) -> str``             -> evolve._derive_toolbox
- ``error_analyst(client, model, session, skill, tools) -> str|None``
- ``publish(skill_dir, run_dir) -> dict`` -> tools.push_skill_to_registry

Every hook delegates to the lab function that already implements the
behavior; this module only adapts signatures. The one behavior added
here: ``score`` backs up and restores the live ``SKILL.md`` around
``score_candidate`` (which installs the candidate by file copy and,
per its docstring, leaves save/restore to the caller).
"""

from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import sys
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# The job's CWD is its own app dir, not this repo's clone, while the lab's
# env conventions (AGENT_REGISTRY, EVAL_QUESTIONS_FILE) are repo-relative
# paths resolved against CWD. Re-anchor them to this repo before any lab
# module reads them at import time. Export the repo root on PYTHONPATH
# too: lab scripts spawn helper subprocesses (e.g. the traffic generator)
# that import the ``agents`` package and inherit only the environment.
for _var in ("AGENT_REGISTRY", "EVAL_QUESTIONS_FILE"):
    _val = os.environ.get(_var)
    if _val and not os.path.isabs(_val) and not os.path.exists(_val):
        _anchored = os.path.join(_REPO_ROOT, _val)
        if os.path.exists(_anchored):
            os.environ[_var] = _anchored

_pythonpath = os.environ.get("PYTHONPATH", "")
if _REPO_ROOT not in _pythonpath.split(os.pathsep):
    os.environ["PYTHONPATH"] = (
        _REPO_ROOT + os.pathsep + _pythonpath if _pythonpath else _REPO_ROOT
    )

logger = logging.getLogger(__name__)


def traffic(run_dir: str) -> dict:
    """Generate evaluation traffic into ``<run_dir>/traffic.json``.

    Questions come from ``EVAL_QUESTIONS_FILE`` (the lab's canonical
    seam, re-read at call time); ``TRAFFIC_MODE=deployed`` drives the
    live Agent Engine stack, anything else runs local in-process agents.
    """
    from agents.workflow.skill_evolution_agent.main import (
        _run_traffic_orchestration,
    )
    from agents.workflow.skill_evolution_agent.tools import _questions_file

    os.makedirs(run_dir, exist_ok=True)
    output_path = os.path.join(run_dir, "traffic.json")
    return _run_traffic_orchestration(output_path, _questions_file())


def score(candidate: str, skill_dir: str, run_dir: str) -> dict:
    """Score a candidate SKILL.md with the lab's judge over the eval set.

    Delegates to ``tools.score_candidate`` (local traffic + judge via
    score_conversations.py + two-defect eval spec), restoring the
    incumbent ``SKILL.md`` afterwards — score_candidate installs the
    candidate by copying it over the live file and leaves it there.
    """
    from agents.workflow.skill_evolution_agent.tools import (
        _resolve_skill_dir,
        score_candidate,
    )

    resolved_dir = _resolve_skill_dir(skill_dir)
    live_skill = os.path.join(resolved_dir, "SKILL.md")
    backup = None
    if os.path.isfile(live_skill):
        fd, backup = tempfile.mkstemp(suffix=".SKILL.md.bak")
        os.close(fd)
        shutil.copy2(live_skill, backup)
    try:
        return score_candidate(candidate, skill_dir, run_dir)
    finally:
        if backup:
            shutil.copy2(backup, live_skill)
            os.unlink(backup)


def gate(run_dir: str, version: str, agent: str):
    """Publish gate: full pytest golden suite against the evolved skill.

    Returns the lab's three-valued verdict: ``(True, detail)`` pass,
    ``(False, detail)`` refusal, ``(None, detail)`` inconclusive (the
    job treats only an explicit ``False`` as a refusal).
    """
    from agents.workflow.skill_evolution_agent.tools import (
        _publish_gate_check,
    )

    return _publish_gate_check(run_dir, version, agent)


def toolbox(agent: str) -> str:
    """Tool descriptions for error analysts, introspected from the
    live local supervisor (root agent or a sub-agent matched by name)."""
    from agents.workflow.skill_evolution_agent.evolve import _derive_toolbox

    return _derive_toolbox(agent)


def error_analyst(client, model, session, skill, tools) -> str | None:  # noqa: ARG001
    """Agentic per-failure analyst with policy/date tool access."""
    from agents.workflow.skill_evolution_agent.agentic_analyst import (
        run_agentic_analyst,
    )

    return run_agentic_analyst(client, model, session, skill)


def publish(skill_dir: str, run_dir: str) -> dict:
    """Push the accepted skill to the lab's skill registry.

    The job calls this after a real PR is opened, passing the skill
    directory it committed; the registry agent and version label are
    recovered from the registry mapping and the run dir's evolved-skill
    artifacts (``best_vN_skill.md`` / ``vN_<agent>_skill.md``).
    """
    from agents.workflow.skill_evolution_agent.tools import (
        _AGENTS,
        _resolve_skill_dir,
        push_skill_to_registry,
    )

    # The job may pass a path in ITS clone of this repo, so absolute
    # paths need not match the registry's — compare by the registry's
    # relative skill_dir as a path suffix.
    agent = None
    normalized = os.path.normpath(os.path.abspath(skill_dir))
    for name, entry in _AGENTS.items():
        rel = os.path.normpath(str(entry["skill_dir"])).lstrip(os.sep)
        resolved = os.path.normpath(os.path.abspath(_resolve_skill_dir(name)))
        if normalized == resolved or normalized.endswith(os.sep + rel):
            agent = name
            break
    if agent is None:
        return {
            "status": "error",
            "error": f"No registry agent matches skill_dir {skill_dir!r}",
        }

    versions = []
    for path in glob.glob(os.path.join(run_dir, "*_skill.md")):
        m = re.match(
            rf"(?:best_)?v(\d+)(?:_{re.escape(agent)})?_skill\.md$",
            os.path.basename(path),
        )
        if m:
            versions.append(int(m.group(1)))
    if not versions:
        return {
            "status": "error",
            "error": f"No evolved skill artifacts found in {run_dir!r}",
        }
    version = f"v{max(versions)}"
    logger.info(
        "Publishing %s %s from %s to the skill registry", agent, version, run_dir
    )
    return push_skill_to_registry(run_dir, version=version, agent=agent)
