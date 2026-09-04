"""
Tests for Discovery Analyzer.
"""
import pytest
from pathlib import Path
from aips_analyzer.analyzers import discovery
from aips_analyzer.evidence import EvidenceBuilder

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_project"


def make_evidence():
    return EvidenceBuilder()


class TestDiscovery:
    def test_basic_discovery(self):
        """Discovery runs without errors on fixture project."""
        ev = make_evidence()
        result = discovery.run(FIXTURE_DIR, ev)
        assert result.success
        assert result.data is not None

    def test_file_count_positive(self):
        ev = make_evidence()
        result = discovery.run(FIXTURE_DIR, ev)
        assert result.data["total_files"] > 0

    def test_python_files_detected(self):
        ev = make_evidence()
        result = discovery.run(FIXTURE_DIR, ev)
        assert result.data["python_files_count"] > 0

    def test_test_files_detected(self):
        ev = make_evidence()
        result = discovery.run(FIXTURE_DIR, ev)
        # test_blog.py should be detected
        assert result.data["test_files_count"] >= 1

    def test_django_app_heuristic(self):
        ev = make_evidence()
        result = discovery.run(FIXTURE_DIR, ev)
        # blog/ should be detected as a Django app (has models.py + views.py)
        apps = result.data["django_apps_heuristic"]
        assert any("blog" in app for app in apps)

    def test_excluded_dirs_not_counted(self):
        """Files in .git, __pycache__ etc. should not be counted."""
        ev = make_evidence()
        result = discovery.run(FIXTURE_DIR, ev)
        # This should not crash and counts should be reasonable
        assert result.data["total_files"] < 10000

    def test_config_flags_detected(self):
        ev = make_evidence()
        result = discovery.run(FIXTURE_DIR, ev)
        flags = result.data["config_flags"]
        assert "pyproject.toml" in flags
        assert flags["pyproject.toml"] is True

    def test_evidence_items_generated(self):
        ev = make_evidence()
        discovery.run(FIXTURE_DIR, ev)
        assert ev.count > 0

    def test_nonexistent_project(self):
        """Should not crash on nonexistent path — let caller handle."""
        ev = make_evidence()
        # If the path doesn't exist, we should get a graceful result or exception
        # (analyzer.py handles the FileNotFoundError, not individual analyzers)
        nonexistent = Path("/this/path/does/not/exist/12345")
        result = discovery.run(nonexistent, ev)
        # It should either succeed with 0 files or fail gracefully
        assert not result.success or result.data.get("total_files", 0) == 0


class TestDiscoveryWalker:
    def test_walk_excludes_pycache(self, tmp_path):
        """__pycache__ directories should be excluded."""
        # Create structure
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "module.pyc").write_bytes(b"")
        (tmp_path / "app.py").write_text("print('hello')")

        ev = make_evidence()
        result = discovery.run(tmp_path, ev)
        assert result.data["total_files"] == 1  # only app.py

    def test_walk_excludes_venv(self, tmp_path):
        """venv/.venv directories should be excluded."""
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "lib" ).mkdir()
        (venv / "lib" / "python.py").write_text("")
        (tmp_path / "myapp.py").write_text("x = 1")

        ev = make_evidence()
        result = discovery.run(tmp_path, ev)
        assert result.data["total_files"] == 1

    def test_files_by_type(self, tmp_path):
        """File type classification should work correctly."""
        (tmp_path / "a.py").write_text("x = 1")
        (tmp_path / "b.py").write_text("y = 2")
        (tmp_path / "style.css").write_text("body {}")
        (tmp_path / "index.html").write_text("<html/>")

        ev = make_evidence()
        result = discovery.run(tmp_path, ev)
        assert result.data["python_files_count"] == 2
        assert result.data["css_files_count"] == 1
        assert result.data["html_files_count"] == 1
