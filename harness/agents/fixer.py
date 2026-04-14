"""Fixer agent — Fozzie.

Attempts automated fixes for auto_fix findings within the configured blast
radius. Downgrades to human_issue if blast radius would be exceeded.
Returns a FixerOutput.
"""
from __future__ import annotations

import logging

from harness.agents.base import BaseAgent
from harness.schemas import Finding, FixerConfig, FixerOutput

logger = logging.getLogger(__name__)


class FixerAgent(BaseAgent):
    role = "fixer"
    default_name = "Fozzie"
    output_schema = FixerOutput
    prompt_file = "fixer.md"

    def __init__(self, config: FixerConfig, llm, gate, repo_root=None) -> None:
        super().__init__(config, llm, gate, repo_root)
        self._fixer_config = config

    def run_on_findings(self, findings: list[Finding]) -> FixerOutput:
        # Only pass auto_fix findings that are in eligible categories.
        eligible = self._filter_eligible(findings)
        ineligible = [f for f in findings if f not in eligible]

        if ineligible:
            logger.info(
                "[%s] %d finding(s) ineligible for auto-fix (category or triage decision)",
                self.name,
                len(ineligible),
            )

        payload = {
            "findings": [f.model_dump() for f in eligible],
            "ineligible_findings": [f.model_dump() for f in ineligible],
            "eligible_categories": self._fixer_config.eligible_categories,
            "max_files_changed": self._fixer_config.max_files_changed,
            "max_lines_changed": self._fixer_config.max_lines_changed,
        }
        return self.run(payload)  # type: ignore[return-value]

    def _filter_eligible(self, findings: list[Finding]) -> list[Finding]:
        """Return findings with decision=auto_fix and an eligible category."""
        eligible_categories = [c.lower() for c in self._fixer_config.eligible_categories]
        result = []
        for f in findings:
            if f.decision != "auto_fix":
                continue
            if eligible_categories:
                category_lower = f.category.lower()
                if not any(ec in category_lower for ec in eligible_categories):
                    logger.info(
                        "[%s] finding %s category %r not in eligible_categories — downgrading to human_issue",
                        self.name,
                        f.id,
                        f.category,
                    )
                    f = f.model_copy(
                        update={
                            "decision": "human_issue",
                            "escalation_reason": "category not in fixer eligible_categories",
                        }
                    )
            result.append(f)
        return result
