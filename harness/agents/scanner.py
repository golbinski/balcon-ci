"""Scanner agent — Statler.

Finds potential issues in the diff (review/review+fix) or in arborist
semantic chunks (scan mode). Returns a ScannerOutput.
"""

from __future__ import annotations

from typing import Any

from harness.agents.base import BaseAgent
from harness.schemas import ScannerConfig, ScannerOutput


class ScannerAgent(BaseAgent):
    role = "scanner"
    default_name = "Statler"
    output_schema = ScannerOutput
    prompt_file = "scanner.md"

    def __init__(self, config: ScannerConfig, llm, gate, repo_root=None) -> None:
        super().__init__(config, llm, gate, repo_root)
        self._scanner_config = config

    def run_on_diff(self, diff: str, files_scanned: list[str]) -> ScannerOutput:
        payload = {
            "source": "diff",
            "diff": diff,
            "files_scanned": files_scanned,
            "min_severity": self._scanner_config.min_severity,
        }
        return self.run(payload)  # type: ignore[return-value]

    def run_on_chunks(
        self,
        chunks: list[dict[str, Any]],
        queries_used: list[str],
        files_scanned: list[str],
    ) -> ScannerOutput:
        payload = {
            "source": "arborist",
            "chunks": chunks,
            "queries_used": queries_used,
            "files_scanned": files_scanned,
            "min_severity": self._scanner_config.min_severity,
        }
        return self.run(payload)  # type: ignore[return-value]
