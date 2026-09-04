"""
Tests for Dependencies Analyzer.
"""
import pytest
from pathlib import Path
from aips_analyzer.analyzers import dependencies
from aips_analyzer.evidence import EvidenceBuilder

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_project"


def make_evidence():
    return EvidenceBuilder()


class TestDependencies:
    def test_runs_without_error(self):
        ev = make_evidence()
        result = dependencies.run(FIXTURE_DIR, ev)
        assert result.success

    def test_detects_python_deps(self):
        ev = make_evidence()
        result = dependencies.run(FIXTURE_DIR, ev)
        py = result.data.get("python", {})
        assert py.get("production_count", 0) > 0

    def test_detects_dev_deps(self):
        ev = make_evidence()
        result = dependencies.run(FIXTURE_DIR, ev)
        py = result.data.get("python", {})
        assert py.get("dev_count", 0) > 0

    def test_production_deps_have_names(self):
        ev = make_evidence()
        result = dependencies.run(FIXTURE_DIR, ev)
        py = result.data.get("python", {})
        for dep in py.get("production", []):
            assert "name" in dep
            assert dep["name"]  # non-empty

    def test_no_code_execution(self, tmp_path):
        """
        Dependencies analyzer must not execute any project code.
        We verify by checking that pip install / setup.py are not called.
        (Structural test: if analyzer runs on invalid Python project, it should not crash)
        """
        # Create a requirements.txt that would fail if pip was run
        (tmp_path / "requirements.txt").write_text("nonexistent-package-xyz==999.0.0\n")
        ev = make_evidence()
        result = dependencies.run(tmp_path, ev)
        # Should succeed (just parse the file, not install anything)
        assert result.success
        assert result.data["python"]["production_count"] == 1

    def test_missing_files_graceful(self, tmp_path):
        """No requirements files should return empty results without crash."""
        ev = make_evidence()
        result = dependencies.run(tmp_path, ev)
        assert result.success
        assert result.data["total_dependencies"] == 0

    def test_lockfile_detection(self, tmp_path):
        """Lockfile presence should be detected."""
        (tmp_path / "uv.lock").write_text("# uv lockfile\n")
        ev = make_evidence()
        result = dependencies.run(tmp_path, ev)
        assert result.data["python"]["lockfile_present"] is True
        assert result.data["python"]["lockfile_file"] == "uv.lock"

    def test_requirements_txt_parsing(self, tmp_path):
        """Standard requirements.txt should be parsed correctly."""
        (tmp_path / "requirements.txt").write_text(
            "django==5.0.0\n"
            "celery>=5.3,<6.0\n"
            "# comment line\n"
            "\n"
            "psycopg2-binary\n"
        )
        ev = make_evidence()
        result = dependencies.run(tmp_path, ev)
        py = result.data["python"]
        names = [d["name"].lower() for d in py["production"]]
        assert "django" in names
        assert "celery" in names
        assert "psycopg2-binary" in names

    def test_package_json_parsing(self, tmp_path):
        """package.json should be parsed for Node deps."""
        import json
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"htmx.org": "^1.9.0"},
            "devDependencies": {"webpack": "^5.0.0"},
        }))
        ev = make_evidence()
        result = dependencies.run(tmp_path, ev)
        nd = result.data["node"]
        assert nd["production_count"] == 1
        assert nd["dev_count"] == 1
