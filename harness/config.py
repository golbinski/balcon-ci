"""
Config loading for BalconCI.

Reads .github/balcon-ci.yml from the repo root and returns a validated BalconConfig.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from harness.schemas import BalconConfig

logger = logging.getLogger(__name__)


def load_config(repo_root: Path) -> BalconConfig:
    """Parse .github/balcon-ci.yml and return a validated BalconConfig.

    Falls back to defaults if the file does not exist.
    """
    config_path = repo_root / ".github" / "balcon-ci.yml"
    if not config_path.exists():
        logger.warning("No .github/balcon-ci.yml found at %s; using defaults", repo_root)
        return BalconConfig()

    with config_path.open() as fh:
        raw = yaml.safe_load(fh) or {}

    return BalconConfig.model_validate(raw)


def load_file_content(repo_root: Path, paths: list[str]) -> str:
    """Read and concatenate the contents of the given repo-relative file paths.

    Missing files are logged and skipped rather than raising.
    """
    parts: list[str] = []
    for rel_path in paths:
        full = repo_root / rel_path
        if not full.exists():
            logger.warning("Instruction/context file not found: %s", full)
            continue
        parts.append(f"<!-- {rel_path} -->\n{full.read_text()}")
    return "\n\n".join(parts)
