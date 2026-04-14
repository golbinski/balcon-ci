"""
BalconCI CLI entrypoint.

Usage:
    balcon-ci review       --pr 42
    balcon-ci review-fix   --pr 42
    balcon-ci scan

Environment variables (all optional unless noted):
    GITHUB_TOKEN          required — GitHub personal access token
    ANTHROPIC_API_KEY     required — Anthropic API key
    GITHUB_REPOSITORY     required — owner/repo (set automatically by GH Actions)
    BALCON_LLM_PROVIDER   default: anthropic
    BALCON_MODEL          default: claude-sonnet-4-6
    BALCON_TOKEN_BUDGET   default: 500000
    BALCON_DRY_RUN        set to 1 to enable dry-run mode
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stderr,
)


def _dry_run() -> bool:
    return os.environ.get("BALCON_DRY_RUN", "").strip() in ("1", "true", "yes")


def _setup() -> tuple:
    """Return (config, llm, gate, gh, repo_root) — shared across all modes."""
    from harness.config import load_config  # noqa: PLC0415
    from harness.cost_gate import CostGate  # noqa: PLC0415
    from harness.github import GitHubClient  # noqa: PLC0415
    from harness.llm import LLMClient  # noqa: PLC0415

    repo_root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    config = load_config(repo_root)
    llm = LLMClient()
    gate = CostGate()
    gh = GitHubClient()
    return config, llm, gate, gh, repo_root


@click.group()
def cli() -> None:
    """BalconCI — agentic code review pipeline."""


@cli.command()
@click.option("--pr", required=True, type=int, help="PR number to review")
def review(pr: int) -> None:
    """Read-only review: scanner → verifier → triage → reviewer."""
    from harness.pipeline import run_review  # noqa: PLC0415

    config, llm, gate, gh, repo_root = _setup()
    run_review(
        pr_number=pr,
        config=config,
        llm=llm,
        gate=gate,
        gh=gh,
        repo_root=repo_root,
        dry_run=_dry_run(),
    )


@cli.command("review-fix")
@click.option("--pr", required=True, type=int, help="PR number to review and fix")
def review_fix(pr: int) -> None:
    """Review with automated fixes: scanner → verifier → triage → fixer → reviewer."""
    from harness.pipeline import run_review_fix  # noqa: PLC0415

    config, llm, gate, gh, repo_root = _setup()
    run_review_fix(
        pr_number=pr,
        config=config,
        llm=llm,
        gate=gate,
        gh=gh,
        repo_root=repo_root,
        dry_run=_dry_run(),
    )


@cli.command()
def scan() -> None:
    """Periodic codebase scan via arborist-mcp embeddings."""
    from harness.pipeline import run_scan  # noqa: PLC0415

    config, llm, gate, gh, repo_root = _setup()
    run_scan(
        config=config,
        llm=llm,
        gate=gate,
        gh=gh,
        repo_root=repo_root,
        dry_run=_dry_run(),
    )


if __name__ == "__main__":
    cli()
