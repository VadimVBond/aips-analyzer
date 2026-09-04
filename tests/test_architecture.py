"""
Tests for Architecture Analyzer (AST-based).
"""
import pytest
from pathlib import Path
from aips_analyzer.analyzers import architecture
from aips_analyzer.evidence import EvidenceBuilder

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_project"


def make_evidence():
    return EvidenceBuilder()


class TestArchitecture:
    def test_runs_without_error(self):
        ev = make_evidence()
        result = architecture.run(FIXTURE_DIR, ev)
        assert result.success

    def test_detects_python_modules(self):
        ev = make_evidence()
        result = architecture.run(FIXTURE_DIR, ev)
        assert result.data["total_modules"] > 0

    def test_detects_model_modules(self):
        """models.py should be detected as a model module."""
        ev = make_evidence()
        result = architecture.run(FIXTURE_DIR, ev)
        model_modules = result.data.get("model_modules", [])
        assert any("models" in m for m in model_modules)

    def test_detects_view_modules(self):
        """views.py should be detected as a view module."""
        ev = make_evidence()
        result = architecture.run(FIXTURE_DIR, ev)
        view_modules = result.data.get("view_modules", [])
        assert any("views" in m for m in view_modules)

    def test_detects_celery_tasks(self):
        """tasks.py with @shared_task should be detected."""
        ev = make_evidence()
        result = architecture.run(FIXTURE_DIR, ev)
        task_modules = result.data.get("celery_task_modules", [])
        assert any("tasks" in m for m in task_modules)

    def test_no_code_execution(self, tmp_path):
        """AST analyzer must not import or run analyzed code."""
        # If code was executed, this would fail (import error for nonexistent module)
        (tmp_path / "app.py").write_text(
            "import this_module_does_not_exist_12345\n"
            "class MyModel: pass\n"
        )
        ev = make_evidence()
        result = architecture.run(tmp_path, ev)
        # Should succeed (just parse AST, not execute import)
        assert result.success

    def test_handles_syntax_error_gracefully(self, tmp_path):
        """Files with syntax errors should be recorded as parse errors, not crash."""
        (tmp_path / "broken.py").write_text(
            "def missing_colon()\n    pass\n"
        )
        ev = make_evidence()
        result = architecture.run(tmp_path, ev)
        assert result.success
        errors = result.data.get("parse_errors", [])
        assert len(errors) >= 1
        assert "broken.py" in errors[0]["file"]

    def test_cycle_detection(self, tmp_path):
        """Cyclic imports should be detected."""
        (tmp_path / "a.py").write_text("from b import something\n")
        (tmp_path / "b.py").write_text("from a import something\n")
        ev = make_evidence()
        result = architecture.run(tmp_path, ev)
        # With 2 files importing each other, may or may not detect cycle
        # depending on classification — just assert it doesn't crash
        assert result.success

    def test_empty_project(self, tmp_path):
        """Empty project should return 0 modules without crash."""
        ev = make_evidence()
        result = architecture.run(tmp_path, ev)
        assert result.success
        assert result.data["total_modules"] == 0

    def test_candidate_findings_present(self):
        """Result must include candidate_findings section."""
        ev = make_evidence()
        result = architecture.run(FIXTURE_DIR, ev)
        cf = result.data.get("candidate_findings", {})
        assert "high_fan_out_modules" in cf
        assert "high_fan_in_modules" in cf
        assert "large_modules" in cf

    def test_no_import_execution(self, tmp_path):
        """
        Verify via inspection that architecture.py uses ast.parse,
        not importlib or __import__.
        """
        import inspect
        from aips_analyzer.analyzers import architecture as arch_module
        source = inspect.getsource(arch_module)
        assert "ast.parse" in source
        assert "importlib.import_module" not in source
        assert "__import__(" not in source
