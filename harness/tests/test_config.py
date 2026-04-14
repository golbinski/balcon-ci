"""Tests for harness/config.py — config loading and file content helpers."""

import textwrap

from harness.config import load_config, load_file_content
from harness.schemas import BalconConfig


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = load_config(tmp_path)
        assert isinstance(cfg, BalconConfig)
        assert cfg.agents.scanner.min_severity == "low"

    def test_empty_yaml_returns_defaults(self, tmp_path):
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "balcon-ci.yml").write_text("")
        cfg = load_config(tmp_path)
        assert isinstance(cfg, BalconConfig)

    def test_full_config_parsed_correctly(self, tmp_path):
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "balcon-ci.yml").write_text(
            textwrap.dedent("""\
                agents:
                  scanner:
                    name: statler
                    min_severity: high
                  verifier:
                    confidence_threshold: 0.8
                  triage:
                    always_escalate:
                      - "race condition"
                      - "security vulnerability"
                  fixer:
                    eligible_categories:
                      - "missing null check"
                    max_files_changed: 2
                    max_lines_changed: 30
                  reviewer:
                    max_iterations: 2
                codebase:
                  scanning:
                    queries:
                      - "raw owning pointers"
                    exclude_paths:
                      - "third_party/**"
            """)
        )
        cfg = load_config(tmp_path)

        assert cfg.agents.scanner.name == "statler"
        assert cfg.agents.scanner.min_severity == "high"
        assert cfg.agents.verifier.confidence_threshold == 0.8
        assert cfg.agents.triage.always_escalate == ["race condition", "security vulnerability"]
        assert cfg.agents.fixer.eligible_categories == ["missing null check"]
        assert cfg.agents.fixer.max_files_changed == 2
        assert cfg.agents.fixer.max_lines_changed == 30
        assert cfg.agents.reviewer.max_iterations == 2
        assert cfg.codebase.scanning.queries == ["raw owning pointers"]
        assert cfg.codebase.scanning.exclude_paths == ["third_party/**"]

    def test_partial_config_fills_remaining_defaults(self, tmp_path):
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "balcon-ci.yml").write_text(
            "agents:\n  scanner:\n    min_severity: critical\n"
        )
        cfg = load_config(tmp_path)
        assert cfg.agents.scanner.min_severity == "critical"
        # Other agents keep their defaults
        assert cfg.agents.verifier.confidence_threshold == 0.5
        assert cfg.agents.reviewer.max_iterations == 3


class TestLoadFileContent:
    def test_single_file_included(self, tmp_path):
        f = tmp_path / "instructions.md"
        f.write_text("Do not auto-fix security issues.")
        result = load_file_content(tmp_path, ["instructions.md"])
        assert "Do not auto-fix security issues." in result
        assert "instructions.md" in result  # comment header

    def test_multiple_files_concatenated(self, tmp_path):
        (tmp_path / "a.md").write_text("Content A")
        (tmp_path / "b.md").write_text("Content B")
        result = load_file_content(tmp_path, ["a.md", "b.md"])
        assert "Content A" in result
        assert "Content B" in result

    def test_missing_file_skipped_without_error(self, tmp_path):
        result = load_file_content(tmp_path, ["nonexistent.md"])
        assert result == ""

    def test_mix_of_present_and_missing_files(self, tmp_path):
        (tmp_path / "present.md").write_text("Hello")
        result = load_file_content(tmp_path, ["nonexistent.md", "present.md"])
        assert "Hello" in result

    def test_empty_paths_list_returns_empty_string(self, tmp_path):
        assert load_file_content(tmp_path, []) == ""
