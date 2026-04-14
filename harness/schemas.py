"""
Pydantic v2 models for BalconCI — matches SPECIFICATION.md §6 exactly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


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
    verified: Optional[bool] = None
    confidence_adjusted: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    rejection_reason: Optional[str] = None

    # Added by triage
    decision: Optional[Literal["auto_fix", "human_issue", "skip"]] = None
    escalation_reason: Optional[str] = None

    # Added by fixer
    fix_attempted: Optional[bool] = None
    fix_result: Optional[Literal["success", "partial", "failed"]] = None
    files_changed: Optional[list[str]] = None
    lines_changed: Optional[int] = None
    fix_summary: Optional[str] = None

    # Added by reviewer
    review_result: Optional[Literal["approved", "changes_requested"]] = None
    review_iterations: Optional[int] = None
    review_feedback: Optional[str] = None
    github_ref: Optional[str] = None

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
    feedback: Optional[str] = None
    reasoning: str


# ---------------------------------------------------------------------------
# Per-agent config models
# ---------------------------------------------------------------------------

class AgentConfig(BaseModel):
    name: Optional[str] = None
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
