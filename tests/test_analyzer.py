"""
Integration tests for the main AIPS Analyzer engine.
Tests analyzer isolation (one failing analyzer should not stop others).
"""
import pytest
from pathlib import Path
from unittest.mock import patch
from aips_analyzer.analyzer import analyze_project
from aips_analyzer.models import EvidenceReport

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_project"


class TestAnalyzerEngine:
    def test_returns_evidence_report(self):
        report = analyze_project(FIXTURE_DIR)
        assert isinstance(report, EvidenceReport)

    def test_schema_field_present(self):
        report = analyze_project(FIXTURE_DIR)
        assert report.schema == "aips-evidence/v1"

    def test_all_sections_present(self):
        report = analyze_project(FIXTURE_DIR)
        assert hasattr(report, "discovery")
        assert hasattr(report, "technology")
        assert hasattr(report, "repository")
        assert hasattr(report, "dependencies")
        assert hasattr(report, "git")
        assert hasattr(report, "architecture")

    def test_evidence_items_generated(self):
        report = analyze_project(FIXTURE_DIR)
        assert len(report.evidence) > 0

    def test_evidence_ids_are_sequential(self):
        report = analyze_project(FIXTURE_DIR)
        ids = [e.id for e in report.evidence]
        assert ids[0] == "E-001"
        for i, eid in enumerate(ids, start=1):
            assert eid == f"E-{i:03d}"

    def test_project_metadata_present(self):
        report = analyze_project(FIXTURE_DIR)
        assert report.project["name"] == "sample_project"
        assert "analyzed_at" in report.project
        assert "analysis_duration_seconds" in report.project

    def test_analyzer_failure_isolation(self):
        """
        If one analyzer crashes, others should still run.
        We mock the git analyzer to raise an exception.
        """
        with patch("aips_analyzer.analyzers.git.run") as mock_git:
            mock_git.side_effect = RuntimeError("Simulated git crash")
            report = analyze_project(FIXTURE_DIR)

        # Other analyzers should have run
        assert report.discovery.get("total_files", 0) > 0
        assert len(report.warnings) >= 1

        # Warning should mention git
        git_warnings = [w for w in report.warnings if w.analyzer == "git"]
        assert len(git_warnings) >= 1

    def test_nonexistent_project_raises(self):
        with pytest.raises(FileNotFoundError):
            analyze_project("/this/path/does/not/exist/aips_test_12345")

    def test_output_saved_to_disk(self, tmp_path):
        output_dir = tmp_path / "output"
        report = analyze_project(FIXTURE_DIR, output_dir=output_dir)
        expected = output_dir / "sample_project" / "evidence.json"
        assert expected.exists()
        assert expected.stat().st_size > 0

    def test_output_is_valid_json(self, tmp_path):
        import json
        output_dir = tmp_path / "output"
        analyze_project(FIXTURE_DIR, output_dir=output_dir)
        evidence_path = output_dir / "sample_project" / "evidence.json"
        data = json.loads(evidence_path.read_text())
        assert data["schema"] == "aips-evidence/v1"
        assert "evidence" in data
        assert "warnings" in data

    def test_to_dict_is_serializable(self):
        import json
        report = analyze_project(FIXTURE_DIR)
        d = report.to_dict()
        # Should not raise
        serialized = json.dumps(d, default=str)
        assert len(serialized) > 100
