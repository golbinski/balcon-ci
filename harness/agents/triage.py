"""Triage agent — Sam.

Routes each verified finding: auto_fix, human_issue, or skip.
Respects always_escalate patterns. Returns a TriageOutput.
"""

from __future__ import annotations

from harness.agents.base import BaseAgent
from harness.schemas import Finding, TriageConfig, TriageOutput


class TriageAgent(BaseAgent):
    role = "triage"
    default_name = "Sam"
    output_schema = TriageOutput
    prompt_file = "triage.md"

    def __init__(self, config: TriageConfig, llm, gate, repo_root=None) -> None:
        super().__init__(config, llm, gate, repo_root)
        self._triage_config = config

    def run_on_findings(self, findings: list[Finding]) -> TriageOutput:
        payload = {
            "findings": [f.model_dump() for f in findings],
            "always_escalate": self._triage_config.always_escalate,
        }
        return self.run(payload)  # type: ignore[return-value]
