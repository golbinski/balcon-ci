"""Reviewer agent — Kermit.

Reviews fixer output, iterates up to max_iterations, marks PR ready for human.
Returns a ReviewerOutput.
"""

from __future__ import annotations

import logging

from harness.agents.base import BaseAgent
from harness.schemas import Finding, ReviewerConfig, ReviewerOutput

logger = logging.getLogger(__name__)


class ReviewerAgent(BaseAgent):
    role = "reviewer"
    default_name = "Kermit"
    output_schema = ReviewerOutput
    prompt_file = "reviewer.md"

    def __init__(
        self, config: ReviewerConfig, llm, gate, repo_root=None, default_model="claude-sonnet-4-6"
    ) -> None:
        super().__init__(config, llm, gate, repo_root, default_model)
        self._reviewer_config = config

    def run_on_findings(
        self,
        findings: list[Finding],
        diff_after_fix: str = "",
        iteration: int = 1,
    ) -> ReviewerOutput:
        payload = {
            "findings": [f.model_dump() for f in findings],
            "diff_after_fix": diff_after_fix,
            "iteration": iteration,
            "max_iterations": self._reviewer_config.max_iterations,
        }
        return self.run(payload)  # type: ignore[return-value]
