"""
Tests for Technology Analyzer.
"""
import pytest
from pathlib import Path
from aips_analyzer.analyzers import technology
from aips_analyzer.evidence import EvidenceBuilder

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_project"


def make_evidence():
    return EvidenceBuilder()


class TestTechnology:
    def test_runs_without_error(self):
        ev = make_evidence()
        result = technology.run(FIXTURE_DIR, ev)
        assert result.success

    def test_detects_django_from_pyproject(self):
        """Django must be detected from pyproject.toml as dependency_declaration."""
        ev = make_evidence()
        result = technology.run(FIXTURE_DIR, ev)
        signals = result.data.get("technology_signals", {})
        assert "Django" in signals
        signal_types = [s["signal_type"] for s in signals["Django"]]
        assert "dependency_declaration" in signal_types

    def test_detects_celery_from_pyproject(self):
        ev = make_evidence()
        result = technology.run(FIXTURE_DIR, ev)
        signals = result.data.get("technology_signals", {})
        assert "Celery" in signals

    def test_signals_have_source_provenance(self):
        """Every signal must have a source with at least one provenance field."""
        ev = make_evidence()
        result = technology.run(FIXTURE_DIR, ev)
        for tech_name, signals in result.data.get("technology_signals", {}).items():
            for signal in signals:
                source = signal.get("source", {})
                assert len(source) > 0, f"Signal for {tech_name} has empty source!"

    def test_observations_not_conclusions(self):
        """
        Technology data must contain 'observations', not a flat 'framework' field.
        Ensures we return evidence, not verdicts.
        """
        ev = make_evidence()
        result = technology.run(FIXTURE_DIR, ev)
        assert "observations" in result.data
        assert "framework" not in result.data
        assert "technology_signals" in result.data

    def test_detects_import_pattern(self, tmp_path):
        """Import-based detection should work from Python source files."""
        (tmp_path / "tasks.py").write_text(
            "from celery import shared_task\n\n@shared_task\ndef my_task(): pass\n"
        )
        ev = make_evidence()
        result = technology.run(tmp_path, ev)
        signals = result.data.get("technology_signals", {})
        assert "Celery" in signals

    def test_empty_project_no_crash(self, tmp_path):
        """Empty project should return empty observations without crash."""
        ev = make_evidence()
        result = technology.run(tmp_path, ev)
        assert result.success

    def test_malformed_requirements(self, tmp_path):
        """Malformed requirements.txt should not crash the analyzer."""
        (tmp_path / "requirements.txt").write_text(
            "# this is a comment\n\n@invalid-package-name###\nnormal-package==1.0\n"
        )
        ev = make_evidence()
        result = technology.run(tmp_path, ev)
        assert result.success

    def test_note_field_present(self):
        """Result must include a note clarifying these are observations."""
        ev = make_evidence()
        result = technology.run(FIXTURE_DIR, ev)
        assert "note" in result.data
