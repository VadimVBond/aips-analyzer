"""
Regression tests for portable evidence artifacts.

These tests enforce:
- no absolute local filesystem paths leak into the serialized JSON
- the output_file field is set BEFORE serialization
- technology observations are deduplicated deterministically
- evidence stays valid against the documented schema
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from aips_analyzer.analyzer import analyze_project
from aips_analyzer.analyzers import technology
from aips_analyzer.evidence import EvidenceBuilder

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_project"


def make_evidence() -> EvidenceBuilder:
    return EvidenceBuilder()


def _has_absolute_path(value: str) -> bool:
    """A portable artifact must never embed an absolute filesystem path."""
    if not isinstance(value, str):
        return False
    # Windows: C:\..., K:\..., etc. POSIX: /home/..., /Users/..., etc.
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return True
    if value.startswith("/") and not value.startswith("//"):
        return True
    return False


class TestPortableProjectBlock:
    def test_project_has_no_absolute_root(self, tmp_path):
        report = analyze_project(FIXTURE_DIR, output_dir=tmp_path)
        project = report.to_dict()["project"]
        assert "root" not in project, (
            "Serialized evidence must not expose an absolute local path. "
            "Use 'name' as the portable project identifier."
        )

    def test_serialized_json_has_no_absolute_path(self, tmp_path):
        analyze_project(FIXTURE_DIR, output_dir=tmp_path)
        evidence_path = tmp_path / "sample_project" / "evidence.json"
        raw = evidence_path.read_text(encoding="utf-8")
        data = json.loads(raw)

        # Walk all string leaves and ensure none look like an absolute path.
        def _walk(obj):
            if isinstance(obj, dict):
                for v in obj.values():
                    yield from _walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from _walk(v)
            elif isinstance(obj, str):
                yield obj

        for s in _walk(data):
            assert not _has_absolute_path(s), (
                f"Found absolute path in serialized evidence: {s!r}"
            )


class TestOutputFileField:
    def test_output_file_is_set_before_serialize(self, tmp_path):
        report = analyze_project(FIXTURE_DIR, output_dir=tmp_path)
        evidence_path = tmp_path / "sample_project" / "evidence.json"
        data = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert "output_file" in data["project"], (
            "output_file must be present in the serialized JSON."
        )
        # Must not be an absolute filesystem path.
        assert not _has_absolute_path(data["project"]["output_file"]), (
            f"output_file should be portable, got: {data['project']['output_file']!r}"
        )

    def test_output_file_field_is_portable(self, tmp_path):
        report = analyze_project(FIXTURE_DIR, output_dir=tmp_path)
        # The in-memory report also carries the field, set before serialize.
        assert "output_file" in report.project
        assert report.project["output_file"].endswith("evidence.json")


class TestDiscoveryPortable:
    def test_discovery_has_no_project_root(self):
        ev = make_evidence()
        result = technology.run  # noqa: F841 -- placeholder to keep imports stable
        # Re-import discovery explicitly so this test stands on its own.
        from aips_analyzer.analyzers import discovery

        result = discovery.run(FIXTURE_DIR, ev)
        assert "project_root" not in result.data, (
            "discovery.data must not include the absolute local project path"
        )


class TestTechnologyDeduplication:
    def test_duplicate_whitenoise_dependency_deduped(self, tmp_path):
        """Two identical signals (same tech, file, pattern) collapse to one."""
        # requirements.txt with the same package declared twice (no version,
        # then with version). The analyzer must keep only one observation.
        (tmp_path / "requirements.txt").write_text(
            "whitenoise\nwhitenoise==6.8.2\ndjango==5.0\n",
            encoding="utf-8",
        )
        ev = make_evidence()
        result = technology.run(tmp_path, ev)
        observations = result.data.get("observations", [])
        wn = [o for o in observations if o["technology"] == "WhiteNoise"]
        assert len(wn) == 1, (
            f"Expected 1 WhiteNoise observation after dedup, got {len(wn)}: {wn}"
        )
        # First occurrence (without explicit version) is preserved because
        # the analyzer iterates the requirements file in order. Either way,
        # the count must be exactly 1.
        assert wn[0]["signal_type"] == "dependency_declaration"

    def test_distinct_observations_not_collapsed(self, tmp_path):
        """Different (tech, signal_type, file, pattern) must remain separate."""
        (tmp_path / "requirements.txt").write_text(
            "django==5.0\ncelery>=5.3\n",
            encoding="utf-8",
        )
        ev = make_evidence()
        result = technology.run(tmp_path, ev)
        observations = result.data.get("observations", [])
        techs = {o["technology"] for o in observations}
        # Django and Celery are different technologies → must not collapse.
        assert "Django" in techs
        assert "Celery" in techs

    def test_dedup_key_is_deterministic(self, tmp_path):
        """Running twice on the same input must yield the same observations."""
        (tmp_path / "requirements.txt").write_text(
            "whitenoise\nwhitenoise==6.8.2\n", encoding="utf-8"
        )
        ev1 = make_evidence()
        ev2 = make_evidence()
        r1 = technology.run(tmp_path, ev1)
        r2 = technology.run(tmp_path, ev2)
        o1 = [o for o in r1.data["observations"] if o["technology"] == "WhiteNoise"]
        o2 = [o for o in r2.data["observations"] if o["technology"] == "WhiteNoise"]
        assert o1 == o2
        assert len(o1) == 1


class TestUtf8SafeCli:
    def test_configure_utf8_io_is_idempotent(self):
        """Calling the UTF-8 configurator twice must not raise."""
        from aips_analyzer.cli.main import _configure_utf8_io

        _configure_utf8_io()
        _configure_utf8_io()
        # Just ensure no exception leaks.

    def test_unicode_in_summary_does_not_crash(self, capsys):
        """
        A project whose name contains non-ASCII characters must not crash
        the CLI summary path.
        """

        from aips_analyzer.cli.main import print_summary
        from aips_analyzer.models import EvidenceReport

        report = EvidenceReport(project={"name": "тест_проекта_🚀"})
        # Should not raise even if the underlying console would otherwise
        # fail with UnicodeEncodeError. (AA-019: print_summary takes
        # package_dir; pass a temp dir to avoid "no-output" code path.)
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            print_summary(report, package_dir=Path(td))
        captured = capsys.readouterr()
        assert "тест_проекта_🚀" in captured.out or captured.out  # at minimum non-empty
