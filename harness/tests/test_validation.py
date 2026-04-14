"""Tests for harness/validation.py — harness-level finding validation."""

from pathlib import Path

from harness.schemas import Finding, FindingLocation
from harness.validation import validate_findings


def _make_finding(
    file: str = "src/main.cpp",
    line_start: int = 5,
    snippet: str = "int* p = new int;",
    confidence: float = 0.8,
    id: str = "test-id",  # noqa: A002
    **kwargs,
) -> Finding:
    return Finding(
        id=id,
        source="diff",
        location=FindingLocation(
            file=file,
            line_start=line_start,
            line_end=line_start,
            snippet=snippet,
        ),
        category="raw pointer",
        severity="high",
        reasoning="Heap allocation without RAII.",
        confidence=confidence,
        **kwargs,
    )


def _write_file(tmp_path: Path, rel: str, lines: list[str]) -> None:
    full = tmp_path / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text("\n".join(lines) + "\n")


class TestValidateFindings:
    def test_valid_finding_passes(self, tmp_path):
        _write_file(
            tmp_path,
            "src/main.cpp",
            ["// line 1", "// line 2", "// line 3", "// line 4", "int* p = new int;"],
        )
        findings = [_make_finding(file="src/main.cpp", line_start=5)]
        result = validate_findings(findings, tmp_path)
        assert len(result) == 1

    def test_nonexistent_file_dropped(self, tmp_path):
        findings = [_make_finding(file="does/not/exist.cpp")]
        result = validate_findings(findings, tmp_path)
        assert result == []

    def test_line_start_zero_dropped(self, tmp_path):
        _write_file(tmp_path, "src/a.cpp", ["int x = 0;"])
        findings = [_make_finding(file="src/a.cpp", line_start=0)]
        result = validate_findings(findings, tmp_path)
        assert result == []

    def test_line_start_beyond_file_length_dropped(self, tmp_path):
        _write_file(tmp_path, "src/a.cpp", ["line1", "line2"])
        findings = [_make_finding(file="src/a.cpp", line_start=99)]
        result = validate_findings(findings, tmp_path)
        assert result == []

    def test_line_start_exactly_at_last_line_passes(self, tmp_path):
        _write_file(tmp_path, "src/a.cpp", ["line1", "line2", "line3"])
        findings = [_make_finding(file="src/a.cpp", line_start=3)]
        result = validate_findings(findings, tmp_path)
        assert len(result) == 1

    def test_multiple_findings_partial_pass(self, tmp_path):
        _write_file(tmp_path, "src/good.cpp", ["int x;", "int y;"])
        findings = [
            _make_finding(file="src/good.cpp", line_start=1),
            _make_finding(file="src/missing.cpp", line_start=1),
        ]
        result = validate_findings(findings, tmp_path)
        assert len(result) == 1
        assert result[0].location.file == "src/good.cpp"

    def test_empty_list_returns_empty(self, tmp_path):
        assert validate_findings([], tmp_path) == []

    def test_all_valid_returns_all(self, tmp_path):
        _write_file(tmp_path, "src/a.cpp", ["a", "b", "c"])
        findings = [
            _make_finding(file="src/a.cpp", line_start=1, id="id-1"),
            _make_finding(file="src/a.cpp", line_start=2, id="id-2"),
            _make_finding(file="src/a.cpp", line_start=3, id="id-3"),
        ]
        result = validate_findings(findings, tmp_path)
        assert len(result) == 3
