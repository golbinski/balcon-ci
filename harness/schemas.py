"""
Pydantic v2 models for BalconCI — matches SPECIFICATION.md §6 exactly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


class FindingLocation(BaseModel):
    file: str
    line_start: int
    line_end: int
    snippet: str


class Finding(BaseModel):
    # Core — set by scanner, immutable after creation
    id: str
    source: Literal["diff", "arborist"]
    location: FindingLocation
    category: str
    severity: Literal["low", "medium", "high", "critical"]
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)

    # Added by verifier
    verified: bool | None = None
    confidence_adjusted: float | None = Field(default=None, ge=0.0, le=1.0)
    rejection_reason: str | None = None

    # Added by triage
    decision: Literal["auto_fix", "human_issue", "skip"] | None = None
    escalation_reason: str | None = None

    # Added by fixer
    fix_attempted: bool | None = None
    fix_result: Literal["success", "partial", "failed"] | None = None
    files_changed: list[str] | None = None
    lines_changed: int | None = None
    fix_summary: str | None = None

    # Added by reviewer
    review_result: Literal["approved", "changes_requested"] | None = None
    review_iterations: int | None = None
    review_feedback: str | None = None
    github_ref: str | None = None

    @field_validator("location")
    @classmethod
    def snippet_non_empty(cls, loc: FindingLocation) -> FindingLocation:
        if not loc.snippet.strip():
            raise ValueError("snippet must be non-empty")
        return loc


# ---------------------------------------------------------------------------
# Agent outputs
# ---------------------------------------------------------------------------


class EvidenceCheck(BaseModel):
    finding_id: str
    file_exists: bool
    line_exists: bool
    snippet_matches: bool
    passed: bool


class ScannerOutput(BaseModel):
    result: Literal["success", "circuit_break"]
    findings: list[Finding]
    scan_metadata: dict  # flexible enough to hold diff or arborist fields
    reasoning: str


class VerifierOutput(BaseModel):
    result: Literal["success", "needs_human", "circuit_break"]
    findings: list[Finding]
    evidence_checks: list[EvidenceCheck]
    reasoning: str


class TriageOutput(BaseModel):
    result: Literal["success", "circuit_break"]
    findings: list[Finding]
    reasoning: str


class FixerOutput(BaseModel):
    result: Literal["success", "partial", "failed", "circuit_break"]
    findings: list[Finding]
    reasoning: str


class ReviewerOutput(BaseModel):
    result: Literal["approved", "changes_requested", "needs_human", "circuit_break"]
    findings: list[Finding]
    feedback: str | None = None
    reasoning: str


# ---------------------------------------------------------------------------
# Per-agent config models
# ---------------------------------------------------------------------------


class AgentConfig(BaseModel):
    name: str | None = None
    instructions: list[str] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)


class ScannerConfig(AgentConfig):
    min_severity: Literal["low", "medium", "high", "critical"] = "low"


class VerifierConfig(AgentConfig):
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class TriageConfig(AgentConfig):
    always_escalate: list[str] = Field(default_factory=list)


class FixerConfig(AgentConfig):
    eligible_categories: list[str] = Field(default_factory=list)
    max_files_changed: int = 5
    max_lines_changed: int = 100


class ReviewerConfig(AgentConfig):
    max_iterations: int = 3


# ---------------------------------------------------------------------------
# Codebase scanning config
# ---------------------------------------------------------------------------


class CodebaseScanningConfig(BaseModel):
    queries: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)


class CodebaseConfig(BaseModel):
    scanning: CodebaseScanningConfig = Field(default_factory=CodebaseScanningConfig)


# ---------------------------------------------------------------------------
# Top-level BalconConfig
# ---------------------------------------------------------------------------


class AgentsConfig(BaseModel):
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    verifier: VerifierConfig = Field(default_factory=VerifierConfig)
    triage: TriageConfig = Field(default_factory=TriageConfig)
    fixer: FixerConfig = Field(default_factory=FixerConfig)
    reviewer: ReviewerConfig = Field(default_factory=ReviewerConfig)


class BalconConfig(BaseModel):
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    codebase: CodebaseConfig = Field(default_factory=CodebaseConfig)
