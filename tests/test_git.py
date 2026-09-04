"""
Tests for Git Analyzer.
"""
import pytest
from pathlib import Path
from aips_analyzer.analyzers import git
from aips_analyzer.evidence import EvidenceBuilder

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_project"


def make_evidence():
    return EvidenceBuilder()


class TestGitAnalyzer:
    def test_runs_without_error(self):
        """Git analyzer should not raise even on non-git directory."""
        ev = make_evidence()
        result = git.run(FIXTURE_DIR, ev)
        # Success regardless of whether git is available
        assert result.data is not None

    def test_non_git_directory(self, tmp_path):
        """Non-git directory should return available=False gracefully."""
        ev = make_evidence()
        result = git.run(tmp_path, ev)
        assert result.data.get("available") is False
        assert result.success  # should NOT crash

    def test_git_repo_detection(self, tmp_path):
        """If .git doesn't exist, available should be False."""
        ev = make_evidence()
        result = git.run(tmp_path, ev)
        assert result.data["available"] is False

    def test_real_git_repo(self):
        """Test against the actual aips-analyzer repo."""
        real_repo = Path(__file__).parent.parent  # aips-analyzer root
        ev = make_evidence()
        result = git.run(real_repo, ev)
        # Either git is available and data is populated, or it's not
        data = result.data
        if data.get("available"):
            assert "current_branch" in data
            assert "total_commits" in data
            assert isinstance(data["total_commits"], int)
            assert data["total_commits"] > 0
        else:
            assert "reason" in data or "error" in data

    def test_no_destructive_commands(self, tmp_path):
        """
        Structural test: verify git analyzer only uses allowed commands.
        The _git function only runs commands from a predefined list.
        We verify by checking the source code does not contain forbidden commands.
        """
        import inspect
        from aips_analyzer.analyzers import git as git_module

        source = inspect.getsource(git_module)
        forbidden = ['"git", ["checkout"', '"git", ["pull"', '"git", ["reset"',
                     '"git", ["clean"', '"git", ["commit"', '"git", ["push"']
        for cmd in forbidden:
            assert cmd not in source, f"Forbidden git command found in source: {cmd}"
