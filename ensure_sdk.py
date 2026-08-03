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

"""SDK discovery — finds or auto-clones BigQuery-Agent-Analytics-SDK.

Search order:
  1. ``SDK_DIR`` env var (root of the cloned repo).
  2. Sibling-repo auto-detect (``../BigQuery-Agent-Analytics-SDK``).
  3. Local cache at ``.sdk/BigQuery-Agent-Analytics-SDK`` (auto-cloned).

Usage::

    from ensure_sdk import import_sdk_module

    quality_report = import_sdk_module("quality_report")
    latency_report = import_sdk_module("latency_report")
"""

import importlib
import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__)))
# No baked-in defaults: the SDK source is defined ONCE in .env (see
# .env.example). When a clone or branch sync is needed and these are unset,
# we abort with a clear error instead of guessing.
_SDK_REPO = os.environ.get("SDK_REPO")
_SDK_BRANCH = os.environ.get("SDK_BRANCH")

_MISSING_ENV_MSG = (
    "SDK_REPO and SDK_BRANCH environment variables must be set to clone or "
    "sync the BigQuery-Agent-Analytics-SDK (see .env.example), or set SDK_DIR "
    "to an existing clone."
)
_SDK_LOCAL_DIR = os.path.join(_PROJECT_ROOT, ".sdk", "BigQuery-Agent-Analytics-SDK")

_sdk_scripts_dir = None  # cached after first lookup


def _sync_sdk_branch():
    """Sync the cached clone to SDK_BRANCH: switch branches AND pick up
    updates when the pinned branch itself has moved.

    The pin (``lab-stable``) is a moving branch — lab-required SDK changes
    land on it deliberately. Syncing only on a branch-NAME mismatch left
    existing clones permanently stale on the pinned branch, so the fetch +
    reset now runs on every lookup (a no-op fast-forward when nothing
    changed; ~1s against the remote).
    """
    if not _SDK_BRANCH or not os.path.isdir(_SDK_LOCAL_DIR):
        return
    try:
        current = subprocess.check_output(
            ["git", "-C", _SDK_LOCAL_DIR, "branch", "--show-current"],
            text=True,
        ).strip()
        if current != _SDK_BRANCH:
            logger.info(
                "Switching SDK clone from %s to %s", current, _SDK_BRANCH,
            )
        subprocess.check_call(
            ["git", "-C", _SDK_LOCAL_DIR, "remote", "set-url", "origin", _SDK_REPO],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.check_call(
            ["git", "-C", _SDK_LOCAL_DIR, "fetch", "origin", _SDK_BRANCH, "--depth", "1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # The cache is a shallow single-branch clone: plain `git checkout
        # <branch>` fails there (no remote-tracking ref for other branches,
        # so the switch silently no-ops and the clone stays on the OLD
        # branch). Create/reset the local branch from FETCH_HEAD instead.
        subprocess.check_call(
            ["git", "-C", _SDK_LOCAL_DIR, "checkout", "-B", _SDK_BRANCH,
             "FETCH_HEAD"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        logger.warning("Failed to switch SDK branch: %s", e)


def find_sdk_scripts_dir():
    """Locate the SDK ``scripts/`` directory. Result is cached."""
    global _sdk_scripts_dir
    if _sdk_scripts_dir is not None:
        return _sdk_scripts_dir

    # 1. Explicit env var
    env_dir = os.environ.get("SDK_DIR")
    if env_dir:
        scripts = os.path.join(env_dir, "scripts")
        if os.path.isdir(scripts):
            _sdk_scripts_dir = os.path.abspath(scripts)
            logger.info("Using SDK from SDK_DIR env var: %s", _sdk_scripts_dir)
            # SDK_DIR wins over the SDK_REPO/SDK_BRANCH pin. A profile-level
            # SDK_DIR export pointing at a clone on some other branch has
            # silently bypassed the pin before — make the override loud.
            if _SDK_BRANCH:
                try:
                    current = subprocess.check_output(
                        ["git", "-C", env_dir, "branch", "--show-current"],
                        text=True, stderr=subprocess.DEVNULL,
                    ).strip()
                    if current and current != _SDK_BRANCH:
                        logger.warning(
                            "SDK_DIR overrides the SDK_BRANCH pin: using "
                            "branch %r from %s, but SDK_BRANCH=%r. Unset "
                            "SDK_DIR (env -u SDK_DIR) to honor the pin.",
                            current, env_dir, _SDK_BRANCH,
                        )
                except (subprocess.CalledProcessError, OSError):
                    pass  # not a git checkout — nothing to compare
            return _sdk_scripts_dir

    # 2. Sibling repo
    candidate = os.path.normpath(
        os.path.join(_PROJECT_ROOT, "..", "BigQuery-Agent-Analytics-SDK", "scripts")
    )
    if os.path.isdir(candidate):
        _sdk_scripts_dir = os.path.abspath(candidate)
        logger.info("Using SDK from sibling repo: %s", _sdk_scripts_dir)
        return _sdk_scripts_dir

    # 3. Local cache (already cloned)
    scripts = os.path.join(_SDK_LOCAL_DIR, "scripts")
    if os.path.isdir(scripts):
        if not _SDK_REPO or not _SDK_BRANCH:
            raise RuntimeError(_MISSING_ENV_MSG)
        _sync_sdk_branch()
        _sdk_scripts_dir = os.path.abspath(scripts)
        logger.info("Using SDK from local cache: %s", _sdk_scripts_dir)
        return _sdk_scripts_dir

    # 4. Auto-clone
    if not _SDK_REPO or not _SDK_BRANCH:
        raise RuntimeError(_MISSING_ENV_MSG)
    logger.info("SDK not found. Cloning %s into %s ...", _SDK_REPO, _SDK_LOCAL_DIR)
    os.makedirs(os.path.dirname(_SDK_LOCAL_DIR), exist_ok=True)
    clone_cmd = ["git", "clone", "--depth", "1", "--branch", _SDK_BRANCH]
    clone_cmd += [_SDK_REPO, _SDK_LOCAL_DIR]
    try:
        subprocess.check_call(
            clone_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        # No SDK anywhere and the clone failed (typically: no network).
        # There is nothing to fall back to — fail with the remediation
        # instead of a raw CalledProcessError traceback.
        raise RuntimeError(
            f"Could not clone the SDK from {_SDK_REPO} (branch "
            f"{_SDK_BRANCH}). If this environment has no network access, "
            "set SDK_DIR to an existing clone of "
            "BigQuery-Agent-Analytics-SDK, or place one as a sibling "
            "checkout next to this repo."
        ) from e
    if os.path.isdir(scripts):
        _sdk_scripts_dir = os.path.abspath(scripts)
        logger.info("Using freshly cloned SDK: %s", _sdk_scripts_dir)
        return _sdk_scripts_dir

    return None


def import_sdk_module(module_name):
    """Import a module from the SDK ``scripts/`` directory.

    Args:
        module_name: Name of the module to import (e.g. ``"quality_report"``).

    Returns:
        The imported module.

    Raises:
        ImportError: If the SDK cannot be found or the module does not exist.
    """
    sdk_dir = find_sdk_scripts_dir()
    if not sdk_dir:
        raise ImportError(
            f"Cannot find SDK {module_name}.py. Clone the SDK repo:\n"
            "  git clone https://github.com/GoogleCloudPlatform/BigQuery-Agent-Analytics-SDK\n"
            "and set SDK_DIR to its root directory, e.g.:\n"
            "  export SDK_DIR=/path/to/BigQuery-Agent-Analytics-SDK"
        )
    if sdk_dir not in sys.path:
        sys.path.insert(0, sdk_dir)

    # Use importlib to avoid name collisions with the calling shim module
    return importlib.import_module(module_name)
