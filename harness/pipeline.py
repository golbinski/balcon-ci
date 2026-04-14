"""
Pipeline orchestration for BalconCI.

Three entry points, one per mode:
  run_review        — read-only: scanner → verifier → triage → reviewer
  run_review_fix    — with commits: scanner → verifier → triage → fixer → reviewer
  run_scan          — autonomous: scanner → verifier → triage → fixer → reviewer
                      using arborist-mcp for code retrieval

All three accept dry_run=True to write output to $GITHUB_STEP_SUMMARY instead of
posting to GitHub.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from harness.agents.base import CircuitBreak
from harness.agents.fixer import FixerAgent
from harness.agents.reviewer import ReviewerAgent
from harness.agents.scanner import ScannerAgent
from harness.agents.triage import TriageAgent
from harness.agents.verifier import VerifierAgent
from harness.cost_gate import BudgetExceeded, CostGate
from harness.github import GitHubClient
from harness.llm import LLMClient
from harness.schemas import BalconConfig, Finding
from harness.validation import validate_findings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dry-run output
# ---------------------------------------------------------------------------

def _dry_run_summary(lines: list[str]) -> None:
    """Append lines to $GITHUB_STEP_SUMMARY (no-op if env var not set)."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        for line in lines:
            logger.info("[dry-run] %s", line)
        return
    with open(summary_path, "a") as fh:
        fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _handle_circuit_break(
    exc: CircuitBreak | BudgetExceeded,
    pr_number: int | None,
    gh: GitHubClient | None,
    dry_run: bool,
) -> None:
    msg = f"**balcon-ci circuit break**: {exc}"
    if dry_run:
        _dry_run_summary([f"## Circuit Break\n\n{msg}"])
    elif pr_number and gh:
        gh.post_pr_comment(pr_number, msg)
    else:
        logger.error(msg)


def _build_agents(
    config: BalconConfig,
    llm: LLMClient,
    gate: CostGate,
    repo_root: Path,
) -> tuple[ScannerAgent, VerifierAgent, TriageAgent, FixerAgent, ReviewerAgent]:
    ac = config.agents
    return (
        ScannerAgent(ac.scanner, llm, gate, repo_root),
        VerifierAgent(ac.verifier, llm, gate, repo_root),
        TriageAgent(ac.triage, llm, gate, repo_root),
        FixerAgent(ac.fixer, llm, gate, repo_root),
        ReviewerAgent(ac.reviewer, llm, gate, repo_root),
    )


# ---------------------------------------------------------------------------
# review mode
# ---------------------------------------------------------------------------

def run_review(
    pr_number: int,
    config: BalconConfig,
    llm: LLMClient,
    gate: CostGate,
    gh: GitHubClient,
    repo_root: Path,
    dry_run: bool = False,
) -> None:
    scanner, verifier, triage, _fixer, reviewer = _build_agents(config, llm, gate, repo_root)

    try:
        diff = gh.get_pr_diff(pr_number)
        files = gh.get_pr_files(pr_number)

        # 1. Scanner
        scan_out = scanner.run_on_diff(diff, files)
        if scan_out.result == "circuit_break":
            raise CircuitBreak(scanner.name, "scanner returned circuit_break")
        findings = validate_findings(scan_out.findings, repo_root)

        # 2. Verifier
        ver_out = verifier.run_on_findings(findings)
        if ver_out.result == "circuit_break":
            raise CircuitBreak(verifier.name, "verifier returned circuit_break")
        findings = validate_findings(ver_out.findings, repo_root)

        # 3. Triage
        tri_out = triage.run_on_findings(findings)
        if tri_out.result == "circuit_break":
            raise CircuitBreak(triage.name, "triage returned circuit_break")
        findings = validate_findings(tri_out.findings, repo_root)

        # 4. Reviewer (read-only — no fixer)
        rev_out = reviewer.run_on_findings(findings, diff_after_fix=diff, iteration=1)
        findings = rev_out.findings

        _post_review_results(
            pr_number, scanner.name, verifier.name, triage.name, reviewer.name,
            findings, rev_out, gh, gate, dry_run,
        )

    except (CircuitBreak, BudgetExceeded) as exc:
        _handle_circuit_break(exc, pr_number, gh, dry_run)
        raise


# ---------------------------------------------------------------------------
# review+fix mode
# ---------------------------------------------------------------------------

def run_review_fix(
    pr_number: int,
    config: BalconConfig,
    llm: LLMClient,
    gate: CostGate,
    gh: GitHubClient,
    repo_root: Path,
    dry_run: bool = False,
) -> None:
    scanner, verifier, triage, fixer, reviewer = _build_agents(config, llm, gate, repo_root)

    try:
        diff = gh.get_pr_diff(pr_number)
        files = gh.get_pr_files(pr_number)

        # 1–3 same as review
        scan_out = scanner.run_on_diff(diff, files)
        if scan_out.result == "circuit_break":
            raise CircuitBreak(scanner.name, "scanner returned circuit_break")
        findings = validate_findings(scan_out.findings, repo_root)

        ver_out = verifier.run_on_findings(findings)
        if ver_out.result == "circuit_break":
            raise CircuitBreak(verifier.name, "verifier returned circuit_break")
        findings = validate_findings(ver_out.findings, repo_root)

        tri_out = triage.run_on_findings(findings)
        if tri_out.result == "circuit_break":
            raise CircuitBreak(triage.name, "triage returned circuit_break")
        findings = validate_findings(tri_out.findings, repo_root)

        # 4. Fixer + reviewer loop
        max_iter = config.agents.reviewer.max_iterations
        for iteration in range(1, max_iter + 1):
            fix_out = fixer.run_on_findings(findings)
            if fix_out.result == "circuit_break":
                raise CircuitBreak(fixer.name, "fixer returned circuit_break")
            findings = fix_out.findings

            # Apply file changes unless dry-run
            _apply_fixes(findings, fixer.name, gh, repo_root, pr_number, dry_run)

            # Re-fetch diff after fix
            diff_after = gh.get_pr_diff(pr_number) if not dry_run else diff

            rev_out = reviewer.run_on_findings(
                findings, diff_after_fix=diff_after, iteration=iteration
            )
            findings = rev_out.findings

            if rev_out.result in ("approved", "needs_human"):
                break
            # changes_requested → loop again

        _post_review_results(
            pr_number, scanner.name, verifier.name, triage.name, reviewer.name,
            findings, rev_out, gh, gate, dry_run,
        )

    except (CircuitBreak, BudgetExceeded) as exc:
        _handle_circuit_break(exc, pr_number, gh, dry_run)
        raise


# ---------------------------------------------------------------------------
# scan mode
# ---------------------------------------------------------------------------

def run_scan(
    config: BalconConfig,
    llm: LLMClient,
    gate: CostGate,
    gh: GitHubClient,
    repo_root: Path,
    dry_run: bool = False,
) -> None:
    scanner, verifier, triage, fixer, reviewer = _build_agents(config, llm, gate, repo_root)

    try:
        # Retrieve semantic chunks via arborist-mcp
        queries = config.codebase.scanning.queries
        exclude_paths = config.codebase.scanning.exclude_paths
        chunks, files_scanned = _query_arborist(queries, exclude_paths, repo_root)

        # 1. Scanner (arborist mode)
        scan_out = scanner.run_on_chunks(chunks, queries, files_scanned)
        if scan_out.result == "circuit_break":
            raise CircuitBreak(scanner.name, "scanner returned circuit_break")
        findings = validate_findings(scan_out.findings, repo_root)

        # 2. Verifier
        ver_out = verifier.run_on_findings(findings)
        if ver_out.result == "circuit_break":
            raise CircuitBreak(verifier.name, "verifier returned circuit_break")
        findings = validate_findings(ver_out.findings, repo_root)

        # 3. Triage
        tri_out = triage.run_on_findings(findings)
        if tri_out.result == "circuit_break":
            raise CircuitBreak(triage.name, "triage returned circuit_break")
        findings = validate_findings(tri_out.findings, repo_root)

        # 4. Fixer
        fix_out = fixer.run_on_findings(findings)
        if fix_out.result == "circuit_break":
            raise CircuitBreak(fixer.name, "fixer returned circuit_break")
        findings = fix_out.findings

        # 5. Reviewer
        rev_out = reviewer.run_on_findings(findings, iteration=1)
        findings = rev_out.findings

        # Post results: open issues for human_issue findings, PR for fixed ones
        _post_scan_results(
            findings, scanner.name, verifier.name, triage.name,
            fixer.name, reviewer.name, rev_out, gh, repo_root, gate, dry_run,
        )

    except (CircuitBreak, BudgetExceeded) as exc:
        _handle_circuit_break(exc, None, gh, dry_run)
        raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_fixes(
    findings: list[Finding],
    fixer_name: str,
    gh: GitHubClient,
    repo_root: Path,
    pr_number: int,
    dry_run: bool,
) -> None:
    """Push a commit for each successfully fixed finding (no-op in dry-run)."""
    fixed = [
        f for f in findings
        if f.fix_attempted and f.fix_result == "success" and f.files_changed
    ]
    if not fixed or dry_run:
        if dry_run and fixed:
            _dry_run_summary([
                f"### Would commit fixes\n\n"
                + "\n".join(
                    f"- `{f.location.file}`: {f.fix_summary}" for f in fixed
                )
            ])
        return

    all_files: list[str] = []
    messages: list[str] = []
    for f in fixed:
        all_files.extend(f.files_changed or [])
        messages.append(f.fix_summary or f.category)

    commit_msg = f"[balcon-ci/{fixer_name}] auto-fix: " + "; ".join(messages)
    gh.push_commit(repo_root, list(dict.fromkeys(all_files)), commit_msg)


def _post_review_results(
    pr_number: int,
    scanner_name: str,
    verifier_name: str,
    triage_name: str,
    reviewer_name: str,
    findings: list[Finding],
    rev_out,
    gh: GitHubClient,
    gate: CostGate,
    dry_run: bool,
) -> None:
    from harness.github import GitHubClient as _GH  # noqa: PLC0415
    table = _GH.findings_to_markdown(findings)
    body = (
        f"## balcon-ci review\n\n"
        f"**Result**: `{rev_out.result}`\n\n"
        f"**Token usage**: {gate.used:,} / {gate.budget:,}\n\n"
        f"### Findings\n\n{table}\n\n"
        f"> **{reviewer_name}** — {rev_out.reasoning}"
    )
    if rev_out.result == "changes_requested" and rev_out.feedback:
        body += f"\n\n**Feedback**: {rev_out.feedback}"

    if dry_run:
        _dry_run_summary([body])
    else:
        gh.post_pr_comment(pr_number, body)


def _post_scan_results(
    findings: list[Finding],
    scanner_name: str,
    verifier_name: str,
    triage_name: str,
    fixer_name: str,
    reviewer_name: str,
    rev_out,
    gh: GitHubClient,
    repo_root: Path,
    gate: CostGate,
    dry_run: bool,
) -> None:
    from harness.github import GitHubClient as _GH  # noqa: PLC0415

    human_findings = [f for f in findings if f.decision == "human_issue"]
    fixed_findings = [
        f for f in findings
        if f.fix_attempted and f.fix_result == "success"
    ]

    summary_lines = [
        "## balcon-ci scan results",
        f"**Token usage**: {gate.used:,} / {gate.budget:,}",
        f"**Findings**: {len(findings)} total, "
        f"{len(human_findings)} → human issue, "
        f"{len(fixed_findings)} → auto-fixed",
        "",
        _GH.findings_to_markdown(findings),
    ]

    if dry_run:
        if human_findings:
            summary_lines += ["", "### Would open issues"]
            for f in human_findings:
                summary_lines.append(
                    f"- **{f.category}** in `{f.location.file}:{f.location.line_start}`"
                )
        _dry_run_summary(summary_lines)
        return

    # Open a GitHub issue for each human_issue finding
    for f in human_findings:
        issue_body = (
            f"**Category**: {f.category}\n"
            f"**Severity**: {f.severity}\n"
            f"**File**: `{f.location.file}` line {f.location.line_start}\n\n"
            f"```\n{f.location.snippet}\n```\n\n"
            f"**Reasoning**: {f.reasoning}\n\n"
            f"> Escalation reason: {f.escalation_reason or '—'}\n\n"
            f"_Opened by **{scanner_name}** / triaged by **{triage_name}**_"
        )
        url = gh.open_issue(
            title=f"[balcon-ci] {f.category}: {f.location.file}:{f.location.line_start}",
            body=issue_body,
            labels=["balcon-ci", f.severity],
        )
        # Annotate the finding with the issue URL
        f = f.model_copy(update={"github_ref": url})

    # If there are fixed findings, commit them and open a PR
    if fixed_findings:
        all_files: list[str] = []
        for f in fixed_findings:
            all_files.extend(f.files_changed or [])

        branch = f"balcon-ci/scan-fixes-{_short_sha(repo_root)}"
        _create_and_push_branch(branch, repo_root)
        gh.push_commit(
            repo_root,
            list(dict.fromkeys(all_files)),
            f"[balcon-ci/{fixer_name}] scan auto-fixes",
        )
        default_branch = _default_branch(repo_root)
        pr_body = (
            f"Auto-fixes from balcon-ci scan.\n\n"
            f"> **{reviewer_name}** — {rev_out.reasoning}\n\n"
            + _GH.findings_to_markdown(fixed_findings)
        )
        gh.open_pr(
            head_branch=branch,
            base_branch=default_branch,
            title=f"[balcon-ci] scan auto-fixes ({len(fixed_findings)} findings)",
            body=pr_body,
        )


def _query_arborist(
    queries: list[str],
    exclude_paths: list[str],
    repo_root: Path,
) -> tuple[list[dict], list[str]]:
    """Query arborist-mcp for semantically relevant code chunks.

    Returns (chunks, files_scanned).
    Currently calls arborist-mcp as a subprocess; replace with MCP client
    when the arborist Python SDK stabilises.
    """
    if not queries:
        logger.warning("No arborist queries configured; scanner will receive empty input")
        return [], []

    try:
        result = subprocess.run(
            ["arborist-mcp", "query", "--json"] + queries,
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error("arborist-mcp error: %s", result.stderr)
            return [], []

        import json  # noqa: PLC0415
        data = json.loads(result.stdout)
        chunks = data.get("chunks", [])

        # Apply exclude_paths filter
        if exclude_paths:
            import fnmatch  # noqa: PLC0415
            chunks = [
                c for c in chunks
                if not any(
                    fnmatch.fnmatch(c.get("file", ""), pat)
                    for pat in exclude_paths
                )
            ]

        files_scanned = list({c["file"] for c in chunks if "file" in c})
        return chunks, files_scanned

    except FileNotFoundError:
        logger.error(
            "arborist-mcp not found. Install it or ensure it is on PATH."
        )
        return [], []
    except Exception as exc:  # noqa: BLE001
        logger.error("arborist-mcp query failed: %s", exc)
        return [], []


def _short_sha(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _default_branch(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "origin/HEAD"],
            cwd=repo_root, text=True
        ).strip().removeprefix("origin/")
    except Exception:  # noqa: BLE001
        return "main"


def _create_and_push_branch(branch: str, repo_root: Path) -> None:
    subprocess.run(["git", "checkout", "-b", branch], cwd=repo_root, check=True)
