"""Verifier agent — Waldorf.

Challenges scanner findings, eliminates hallucinations, adjusts confidence.
Returns a VerifierOutput.
"""
from __future__ import annotations

from harness.agents.base import BaseAgent
from harness.schemas import Finding, VerifierConfig, VerifierOutput


class VerifierAgent(BaseAgent):
    role = "verifier"
    default_name = "Waldorf"
    output_schema = VerifierOutput
    prompt_file = "verifier.md"

    def __init__(self, config: VerifierConfig, llm, gate, repo_root=None) -> None:
        super().__init__(config, llm, gate, repo_root)
        self._verifier_config = config

    def run_on_findings(self, findings: list[Finding]) -> VerifierOutput:
        payload = {
            "findings": [f.model_dump() for f in findings],
            "confidence_threshold": self._verifier_config.confidence_threshold,
        }
        return self.run(payload)  # type: ignore[return-value]
