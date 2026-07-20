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

"""Load a skill directory into a system prompt string.

Two sources, selected via env:
  SKILL_SOURCE=file      — read SKILL.md from the packaged skill_dir (default).
  SKILL_SOURCE=registry  — fetch the latest revision from the Agent Platform
                           Skill Registry (GetSkill), unzip, and parse it with
                           the same code path; ANY failure falls back to the
                           packaged skill_dir with a WARNING.

Registry mode needs a skill id (arg or SKILL_REGISTRY_ID env) and the
SkillRegistry client: either a skill_registry.py copied next to this file at
deploy time, or the local SDK clone resolved via ensure_sdk.
"""

import base64
import importlib.util
import io
import logging
import os
import tempfile
import zipfile
from typing import Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# skill_id -> (extracted_dir, revision); one GetSkill per process.
_registry_cache: dict = {}


def _skill_registry_class():
    """Locate the SkillRegistry client class (deployed copy or SDK clone)."""
    candidates = [os.path.join(os.path.dirname(__file__), "skill_registry.py")]
    sdk_dir = os.getenv("SDK_DIR")
    if sdk_dir:
        candidates.append(
            os.path.join(
                sdk_dir, "examples", "skill_evolution_lab", "agent", "skill_registry.py"
            )
        )
    try:
        from ensure_sdk import find_sdk_scripts_dir

        scripts_dir = find_sdk_scripts_dir()
        if scripts_dir:
            candidates.append(
                os.path.join(
                    os.path.dirname(scripts_dir),
                    "examples",
                    "skill_evolution_lab",
                    "agent",
                    "skill_registry.py",
                )
            )
    except ImportError:
        pass
    for path in candidates:
        if os.path.isfile(path):
            spec = importlib.util.spec_from_file_location("ks_skill_registry", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.SkillRegistry
    raise ImportError(
        "skill_registry.py not found (expected a deploy-time copy next to "
        f"skill_loader.py or an SDK clone); searched: {candidates}"
    )


def _find_key(obj, key: str):
    """Depth-first search for a key in nested dicts/lists (API schema drift guard)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_key(item, key)
            if found is not None:
                return found
    return None


def _fetch_registry_skill(skill_id: str) -> Tuple[str, str]:
    """GetSkill -> (extracted skill dir, revision). Raises on any failure."""
    if skill_id in _registry_cache:
        return _registry_cache[skill_id]
    registry_cls = _skill_registry_class()
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("PROJECT_ID")
    if not project:
        raise ValueError("GOOGLE_CLOUD_PROJECT/PROJECT_ID not set")
    location = os.getenv("SKILL_REGISTRY_LOCATION", "us-central1")
    client = registry_cls(project, location)
    # Prefer the newest revision: GetSkill can serve a stale payload after
    # updates (observed live); get_latest reads via GetSkillRevision.
    skill = getattr(client, "get_latest", client.get)(skill_id)
    payload = _find_key(skill, "zippedFilesystem")
    if not payload:
        raise KeyError(
            f"GetSkill({skill_id}) returned no zippedFilesystem payload; "
            f"top-level keys: {sorted(skill)}"
        )
    out_dir = tempfile.mkdtemp(prefix=f"skill_registry_{skill_id}_")
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(payload))) as zf:
        zf.extractall(out_dir)
    # GetSkill carries no revision id (verified live 2026-07-14); identify the
    # served payload by its sha256 instead.
    revision = (
        _find_key(skill, "revisionId")
        or (skill.get("sha256") or "")[:12]
        or "unknown"
    )
    _registry_cache[skill_id] = (out_dir, str(revision))
    return _registry_cache[skill_id]


def _resolve_skill_dir(skill_dir: str, skill_id: Optional[str] = None) -> str:
    """Pick the directory to parse: registry download or the packaged one."""
    skill_id = skill_id or os.getenv("SKILL_REGISTRY_ID")
    if os.getenv("SKILL_SOURCE", "file").lower() != "registry" or not skill_id:
        return skill_dir
    try:
        registry_dir, revision = _fetch_registry_skill(skill_id)
        if not os.path.isfile(os.path.join(registry_dir, "SKILL.md")):
            raise FileNotFoundError("registry payload contains no SKILL.md")
        logger.info(
            "Loaded skill from registry %s (revision %s)", skill_id, revision
        )
        return registry_dir
    except Exception as e:
        logger.warning(
            "Registry skill fetch failed for %s (%s); falling back to file %s",
            skill_id,
            e,
            skill_dir,
        )
        return skill_dir


def load_skill_metadata(skill_dir: str, skill_id: Optional[str] = None) -> dict:
    """Parse YAML frontmatter from SKILL.md and return metadata dict."""
    skill_dir = _resolve_skill_dir(skill_dir, skill_id)
    skill_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_path):
        return {}

    with open(skill_path) as f:
        content = f.read()

    if not content.startswith("---"):
        return {}

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}

    try:
        return yaml.safe_load(parts[1]) or {}
    except Exception:
        logger.warning("Failed to parse SKILL.md frontmatter in %s", skill_dir)
        return {}


def skill_is_baseline(skill_dir: str, skill_id: Optional[str] = None) -> bool:
    """True when the skill's frontmatter version is 0 or absent.

    The production-loop demo keeps deliberately flawed V0 skills on main;
    the evolution loop repairs them through PRs that bump the version.
    Gate tests use this to decide which assertions the current skill can
    honestly be held to.
    """
    meta = load_skill_metadata(skill_dir, skill_id) or {}
    version = str((meta.get("metadata") or {}).get("version", "")).strip()
    return version in ("", "0", "None")


def load_skill(skill_dir: str, skill_id: Optional[str] = None) -> str:
    """Read SKILL.md and reference files into a single prompt string.

    Parses the YAML frontmatter (between --- delimiters) and extracts
    the markdown body as the agent prompt. Appends any .md files from
    the references/ subdirectory.

    Args:
        skill_dir: Path to skill directory containing SKILL.md (also the
            fallback when registry mode is enabled but unavailable).
        skill_id: Skill Registry id; defaults to SKILL_REGISTRY_ID env.
            Only used when SKILL_SOURCE=registry.

    Returns:
        Combined skill text suitable for use as an agent system prompt.

    Raises:
        FileNotFoundError: If SKILL.md doesn't exist.
    """
    skill_dir = _resolve_skill_dir(skill_dir, skill_id)
    skill_path = os.path.join(skill_dir, "SKILL.md")

    if not os.path.exists(skill_path):
        raise FileNotFoundError(f"Skill file not found: {skill_path}")

    with open(skill_path) as f:
        content = f.read()

    # Strip YAML frontmatter, keep markdown body
    if content.startswith("---"):
        parts = content.split("---", 2)
        body = parts[2].strip() if len(parts) >= 3 else content
    else:
        body = content.strip()

    logger.debug("Loaded skill body from %s (%d chars)", skill_path, len(body))

    # Append reference files
    refs_dir = os.path.join(skill_dir, "references")
    if os.path.isdir(refs_dir):
        ref_sections = []
        for fname in sorted(os.listdir(refs_dir)):
            if fname.endswith(".md"):
                ref_path = os.path.join(refs_dir, fname)
                with open(ref_path) as f:
                    ref_content = f.read().strip()
                title = fname.replace(".md", "").replace("_", " ").replace("-", " ").title()
                ref_sections.append(f"## {title}\n\n{ref_content}")
                logger.debug("Loaded reference %s (%d chars)", fname, len(ref_content))
        if ref_sections:
            body += "\n\n---\n\n# Reference Materials\n\n" + "\n\n".join(ref_sections)

    logger.info("Loaded skill: %d chars total", len(body))
    return body
