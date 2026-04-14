"""
GitHub API client for BalconCI.

Wraps PyGitHub to provide the operations needed by the pipeline.
All agent comments are signed with the agent name per spec §7.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from github import Github, Auth
from github.GithubException import GithubException

from harness.schemas import Finding

if TYPE_CHECKING:
    from github.PullRequest import PullRequest
    from github.Repository import Repository

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, repo_full_name: str | None = None) -> None:
        token = os.environ["GITHUB_TOKEN"]
        self._gh = Github(auth=Auth.Token(token))
        name = repo_full_name or os.environ.get("GITHUB_REPOSITORY", "")
        if not name:
            raise ValueError(
                "GitHub repo name not provided and GITHUB_REPOSITORY not set"
            )
        self._repo: Repository = self._gh.get_repo(name)

    # ------------------------------------------------------------------
    # PR helpers
    # ------------------------------------------------------------------

    def get_pr_diff(self, pr_number: int) -> str:
        """Return the unified diff for a pull request."""
        import urllib.request  # noqa: PLC0415

        pr = self._repo.get_pull(pr_number)
        # PyGitHub doesn't expose raw diff directly; use the diff URL
        req = urllib.request.Request(
            pr.diff_url,
            headers={"Authorization": f"token {os.environ['GITHUB_TOKEN']}"},
        )
        with urllib.request.urlopen(req) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def get_pr_files(self, pr_number: int) -> list[str]:
        pr = self._repo.get_pull(pr_number)
        return [f.filename for f in pr.get_files()]

    def post_pr_comment(self, pr_number: int, body: str) -> None:
        pr = self._repo.get_pull(pr_number)
        pr.create_issue_comment(body)
        logger.info("Posted comment on PR #%d", pr_number)

    def post_review(
        self,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
    ) -> None:
        """Post a formal PR review (COMMENT, APPROVE, or REQUEST_CHANGES)."""
        pr = self._repo.get_pull(pr_number)
        pr.create_review(body=body, event=event)
        logger.info("Posted review on PR #%d (event=%s)", pr_number, event)

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def open_issue(self, title: str, body: str, labels: list[str] | None = None) -> str:
        """Open a GitHub issue and return its URL."""
        issue = self._repo.create_issue(
            title=title,
            body=body,
            labels=labels or [],
        )
        logger.info("Opened issue #%d: %s", issue.number, title)
        return issue.html_url

    # ------------------------------------------------------------------
    # PRs (scan mode)
    # ------------------------------------------------------------------

    def open_pr(
        self,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> str:
        """Create a PR from head_branch → base_branch and return its URL."""
        pr = self._repo.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch,
        )
        logger.info("Opened PR #%d: %s", pr.number, title)
        return pr.html_url

    # ------------------------------------------------------------------
    # Commits (review+fix and scan modes)
    # ------------------------------------------------------------------

    def push_commit(
        self,
        repo_root: Path,
        files_changed: list[str],
        message: str,
    ) -> None:
        """Stage files_changed and push a commit on the current branch."""
        for rel_path in files_changed:
            subprocess.run(
                ["git", "add", rel_path],
                cwd=repo_root,
                check=True,
            )
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo_root,
            check=True,
            env={**os.environ, "GIT_AUTHOR_NAME": "balcon-ci", "GIT_AUTHOR_EMAIL": "balcon-ci@github-actions"},
        )
        subprocess.run(
            ["git", "push"],
            cwd=repo_root,
            check=True,
        )
        logger.info("Pushed commit: %s", message[:72])

    # ------------------------------------------------------------------
    # File content
    # ------------------------------------------------------------------

    def get_file_content(self, path: str, ref: str = "HEAD") -> str:
        try:
            contents = self._repo.get_contents(path, ref=ref)
            return contents.decoded_content.decode("utf-8", errors="replace")
        except GithubException as exc:
            logger.warning("Could not fetch %s@%s: %s", path, ref, exc)
            return ""

    # ------------------------------------------------------------------
    # Comment formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def format_agent_comment(agent_name: str, body: str) -> str:
        """Prefix body with the standard agent signature."""
        return f"> **{agent_name}** — {body}"

    @staticmethod
    def findings_to_markdown(findings: list[Finding]) -> str:
        """Render a list of findings as a Markdown table."""
        if not findings:
            return "_No findings._"
        rows = ["| File | Line | Severity | Category | Decision |",
                "|---|---|---|---|---|"]
        for f in findings:
            decision = f.decision or "—"
            rows.append(
                f"| `{f.location.file}` | {f.location.line_start} "
                f"| {f.severity} | {f.category} | {decision} |"
            )
        return "\n".join(rows)
