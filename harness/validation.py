"""
Harness-level finding validation.

Called between every agent pair. Findings that fail any check are dropped
(with a logged reason) before being passed to the next agent.

Checks enforced (spec §6.1):
  - snippet must be non-empty
  - location.file must exist in the repo
  - location.line_start must be a valid line number in that file
  - confidence must be in [0.0, 1.0]
"""
from __future__ import annotations

import logging
from pathlib import Path

from harness.schemas import Finding

logger = logging.getLogger(__name__)


def validate_findings(findings: list[Finding], repo_root: Path) -> list[Finding]:
    """Return only findings that pass all harness checks.

    Each dropped finding is logged with the reason.
    """
    passing: list[Finding] = []

    for f in findings:
        reason = _check(f, repo_root)
        if reason:
            logger.warning(
                "Dropping finding %s (%s:%d): %s",
                f.id,
                f.location.file,
                f.location.line_start,
                reason,
            )
        else:
            passing.append(f)

    logger.info(
        "Validation: %d/%d findings passed", len(passing), len(findings)
    )
    return passing


def _check(finding: Finding, repo_root: Path) -> str | None:
    """Return a failure reason string, or None if the finding is valid."""
    loc = finding.location

    if not loc.snippet.strip():
        return "snippet is empty"

    if not (0.0 <= finding.confidence <= 1.0):
        return f"confidence {finding.confidence} out of [0.0, 1.0]"

    file_path = repo_root / loc.file
    if not file_path.exists():
        return f"file does not exist: {loc.file}"

    try:
        lines = file_path.read_text(errors="replace").splitlines()
    except OSError as exc:
        return f"could not read file: {exc}"

    if loc.line_start < 1 or loc.line_start > len(lines):
        return (
            f"line_start {loc.line_start} out of range "
            f"(file has {len(lines)} lines)"
        )

    return None
