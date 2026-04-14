"""Tests for harness/schemas.py — Finding validation rules."""

import pytest
from pydantic import ValidationError

from harness.schemas import (
    BalconConfig,
    Finding,
    FixerConfig,
    ReviewerConfig,
    ScannerConfig,
    VerifierConfig,
)


def _location(**kwargs) -> dict:
    base = {
        "file": "src/main.cpp",
        "line_start": 10,
        "line_end": 12,
        "snippet": "int* p = new int;",
    }
    return {**base, **kwargs}


def _finding(**kwargs) -> dict:
    base = {
        "id": "abc123",
        "source": "diff",
        "location": _location(),
        "category": "raw owning pointer",
        "severity": "high",
        "reasoning": "Heap allocation without RAII wrapper.",
        "confidence": 0.9,
    }
    return {**base, **kwargs}


class TestFindingValidation:
    def test_valid_finding(self):
        f = Finding.model_validate(_finding())
        assert f.id == "abc123"
        assert f.confidence == 0.9

    def test_empty_snippet_rejected(self):
        with pytest.raises(ValidationError, match="snippet"):
            Finding.model_validate(_finding(location=_location(snippet="")))

    def test_whitespace_only_snippet_rejected(self):
        with pytest.raises(ValidationError, match="snippet"):
            Finding.model_validate(_finding(location=_location(snippet="   \n\t")))

    def test_confidence_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            Finding.model_validate(_finding(confidence=-0.1))

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValidationError):
            Finding.model_validate(_finding(confidence=1.01))

    def test_confidence_boundary_values_accepted(self):
        Finding.model_validate(_finding(confidence=0.0))
        Finding.model_validate(_finding(confidence=1.0))

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            Finding.model_validate(_finding(severity="blocker"))

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            Finding.model_validate(_finding(source="manual"))

    def test_optional_fields_default_to_none(self):
        f = Finding.model_validate(_finding())
        assert f.verified is None
        assert f.decision is None
        assert f.fix_attempted is None
        assert f.review_result is None


class TestAgentConfigs:
    def test_scanner_default_min_severity(self):
        cfg = ScannerConfig()
        assert cfg.min_severity == "low"

    def test_verifier_default_confidence_threshold(self):
        cfg = VerifierConfig()
        assert cfg.confidence_threshold == 0.5

    def test_verifier_confidence_threshold_out_of_range(self):
        with pytest.raises(ValidationError):
            VerifierConfig(confidence_threshold=1.5)

    def test_fixer_defaults(self):
        cfg = FixerConfig()
        assert cfg.max_files_changed == 5
        assert cfg.max_lines_changed == 100
        assert cfg.eligible_categories == []

    def test_reviewer_default_max_iterations(self):
        cfg = ReviewerConfig()
        assert cfg.max_iterations == 3


class TestBalconConfig:
    def test_empty_config_uses_all_defaults(self):
        cfg = BalconConfig()
        assert cfg.agents.scanner.min_severity == "low"
        assert cfg.agents.verifier.confidence_threshold == 0.5
        assert cfg.agents.reviewer.max_iterations == 3
        assert cfg.codebase.scanning.queries == []
        assert cfg.codebase.scanning.exclude_paths == []
