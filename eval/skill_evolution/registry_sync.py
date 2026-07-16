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

"""Sync agent SKILL.md directories with the Agent Platform Skill Registry.

The registry is the runtime source of truth for deployed agents
(SKILL_SOURCE=registry): each update is a new immutable revision. This CLI
keeps the in-repo skill dirs and the registry reconciled.

Commands:
    seed                        Create-or-update every agent that has a
                                skill_id in agent_registry.json (idempotent:
                                skipped when the registry SKILL.md is
                                byte-identical to the local one).
    push --agent NAME           Push a skill dir as a new revision
         [--skill-dir DIR]      (default: the agent's skill_dir).
    revisions --agent NAME      List revisions.
    verify-read --agent NAME    GetSkill, unzip the payload, print revision +
                                SKILL.md head. Proves deployed agents can
                                actually download the skill body.

Reuses the SkillRegistry client from the SDK clone and the fetch/unzip logic
in agents.enterprise.policy_agent.skill_loader (single source of truth).
"""

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("registry_sync")

_HERE = os.path.dirname(os.path.abspath(__file__))


def _find_repo_root(registry_path: str) -> str:
    """Skill dirs in agent_registry.json are relative to the repo root."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(registry_path))))


def _load_registry_config(path=None):
    path = path or os.environ.get(
        "AGENT_REGISTRY", os.path.join(_HERE, "agent_registry.json")
    )
    with open(path) as f:
        config = json.load(f)
    return config, path


def _ensure_repo_on_path(repo_root: str):
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def _registry_client(location: str):
    """Build a SkillRegistry via skill_loader's resolution (SDK copy/clone)."""
    from agents.enterprise.policy_agent.skill_loader import _skill_registry_class

    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("PROJECT_ID")
    if not project:
        raise SystemExit("PROJECT_ID/GOOGLE_CLOUD_PROJECT must be set (source .env)")
    return _skill_registry_class()(project, location)


def _agents_with_skill_id(config, only_agent=None):
    agents = config.get("agents", {})
    selected = {}
    for name, entry in agents.items():
        if only_agent and name != only_agent:
            continue
        if entry.get("skill_id"):
            selected[name] = entry
        elif only_agent:
            raise SystemExit(f"Agent '{name}' has no skill_id in agent_registry.json")
    if only_agent and not selected:
        raise SystemExit(f"Unknown agent '{only_agent}' in agent_registry.json")
    return selected


def _registry_skill_md(skill_id: str) -> str:
    """Fetch the registry's current SKILL.md text ('' when unreadable)."""
    from agents.enterprise.policy_agent import skill_loader

    try:
        skill_dir, _ = skill_loader._fetch_registry_skill(skill_id)
        with open(os.path.join(skill_dir, "SKILL.md")) as f:
            return f.read()
    except Exception as e:
        logger.debug("Could not read registry SKILL.md for %s: %s", skill_id, e)
        return ""


def cmd_seed(args, config, registry_path):
    repo_root = _find_repo_root(registry_path)
    location = config.get("registry_location", "us-central1")
    client = _registry_client(location)
    for name, entry in _agents_with_skill_id(config, args.agent).items():
        skill_id = entry["skill_id"]
        skill_dir = os.path.join(repo_root, entry["skill_dir"])
        local_md_path = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(local_md_path):
            logger.warning("SKIP %s: no SKILL.md at %s", name, skill_dir)
            continue
        if not client.exists(skill_id):
            logger.info("CREATE %s -> %s (revision 1)", name, skill_id)
            client.create(skill_id, skill_dir, description=entry.get("label", name))
            continue
        with open(local_md_path) as f:
            local_md = f.read()
        if _registry_skill_md(skill_id) == local_md:
            logger.info("SKIP %s: registry already matches %s", name, local_md_path)
            continue
        logger.info("UPDATE %s -> %s (new revision)", name, skill_id)
        client.update(skill_id, skill_dir, description=entry.get("label", name))
    print("Seed complete.")


def cmd_push(args, config, registry_path):
    repo_root = _find_repo_root(registry_path)
    location = config.get("registry_location", "us-central1")
    entry = _agents_with_skill_id(config, args.agent)[args.agent]
    skill_id = entry["skill_id"]
    skill_dir = args.skill_dir or os.path.join(repo_root, entry["skill_dir"])
    client = _registry_client(location)
    if client.exists(skill_id):
        client.update(skill_id, skill_dir, description=entry.get("label", args.agent))
    else:
        client.create(skill_id, skill_dir, description=entry.get("label", args.agent))
    revisions = client.list_revisions(skill_id)
    print(f"Pushed {skill_dir} -> {skill_id}; revisions now: {len(revisions)}")


def cmd_revisions(args, config, registry_path):
    location = config.get("registry_location", "us-central1")
    entry = _agents_with_skill_id(config, args.agent)[args.agent]
    client = _registry_client(location)
    revisions = client.list_revisions(entry["skill_id"])
    print(f"{entry['skill_id']}: {len(revisions)} revision(s)")
    for rev in revisions:
        rev_id = rev.get("revisionId") or rev.get("name", "?").split("/")[-1]
        print(f"  - {rev_id}  createTime={rev.get('createTime', '?')}")


def cmd_verify_read(args, config, registry_path):
    from agents.enterprise.policy_agent import skill_loader

    location = config.get("registry_location", "us-central1")
    os.environ.setdefault("SKILL_REGISTRY_LOCATION", location)
    entry = _agents_with_skill_id(config, args.agent)[args.agent]
    skill_id = entry["skill_id"]
    skill_dir, revision = skill_loader._fetch_registry_skill(skill_id)
    md_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(md_path):
        raise SystemExit(
            f"FAIL: payload for {skill_id} extracted to {skill_dir} has no SKILL.md"
        )
    with open(md_path) as f:
        content = f.read()
    print(f"OK: GetSkill({skill_id}) revision={revision} SKILL.md={len(content)} chars")
    print("--- SKILL.md head ---")
    print("\n".join(content.splitlines()[:12]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", help="Path to agent_registry.json")
    sub = parser.add_subparsers(dest="command", required=True)

    p_seed = sub.add_parser("seed", help="Create-or-update all skills (idempotent)")
    p_seed.add_argument("--agent", help="Limit to one agent")

    p_push = sub.add_parser("push", help="Push a skill dir as a new revision")
    p_push.add_argument("--agent", required=True)
    p_push.add_argument("--skill-dir", help="Override the agent's skill_dir")

    p_rev = sub.add_parser("revisions", help="List revisions")
    p_rev.add_argument("--agent", required=True)

    p_ver = sub.add_parser("verify-read", help="GetSkill + unzip + print head")
    p_ver.add_argument("--agent", required=True)

    args = parser.parse_args()
    config, registry_path = _load_registry_config(args.registry)
    _ensure_repo_on_path(_find_repo_root(registry_path))
    os.environ.setdefault(
        "SKILL_REGISTRY_LOCATION", config.get("registry_location", "us-central1")
    )

    handlers = {
        "seed": cmd_seed,
        "push": cmd_push,
        "revisions": cmd_revisions,
        "verify-read": cmd_verify_read,
    }
    handlers[args.command](args, config, registry_path)


if __name__ == "__main__":
    main()
