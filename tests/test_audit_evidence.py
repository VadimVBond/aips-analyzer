"""
Tests for the deterministic Evidence Audit / Contract Input filter
(`scripts/audit_evidence.py`).

We exercise the audit module programmatically (importing from scripts/)
rather than spawning subprocesses, so tests are fast and stable.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
AUDIT_PATH = SCRIPTS_DIR / "audit_evidence.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_evidence", AUDIT_PATH)
    assert spec and spec.loader, "could not load audit_evidence.py"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit = _load_audit_module()


def _evidence_doc(items=None, metrics=None, warnings=None, project=None,
                  schema="aips-evidence/v1", **sections):
    doc = {
        "schema": schema,
        "analyzer": {"name": "aips-analyzer", "version": "0.1.0"},
        "project": project or {"name": "demo", "analyzed_at": "2026-01-01T00:00:00Z"},
        "discovery": {"total_files": 1},
        "technology": {"observations": []},
        "repository": {"total_lines": 100},
        "dependencies": {"python": {"production_count": 0}},
        "git": {"available": False},
        "architecture": {"total_modules": 0},
        "evidence": items if items is not None else [],
        "metrics": metrics if metrics is not None else [],
        "warnings": warnings if warnings is not None else [],
    }
    doc.update(sections)
    return doc


def _tech_obs(tech, signal_type, file, pattern, detail=None, value=None):
    return {
        "id": "E-X",
        "type": "technology",
        "subject": tech,
        "value": value if value is not None else detail or "",
        "source": {
            "file": file,
            "method": "regex_import_scan",
            "pattern": pattern,
        },
        "signal_type": signal_type,
    }


def _metric(name, value):
    return {"name": name, "value": value}


# ─── A. valid evidence.json ───────────────────────────────────────────────


class TestValidDocument:
    def test_header_carries_source_schema(self):
        doc = _evidence_doc(schema="aips-evidence/v1")
        out = audit.audit_evidence(doc)
        assert out["header"]["source_schema"] == "aips-evidence/v1"
        assert out["header"]["schema"] == audit.AUDIT_SCHEMA

    def test_summary_counts_match_input(self):
        items = [
            _tech_obs("Django", "import_pattern", "a.py", "import django"),
            _tech_obs("Celery", "import_pattern", "b.py", "import celery"),
            _tech_obs("Django", "dependency_declaration", "requirements.txt",
                      "django"),
        ]
        metrics = [_metric("discovery.total_files", 5)]
        doc = _evidence_doc(items=items, metrics=metrics)
        out = audit.audit_evidence(doc)
        assert out["summary"]["evidence_count"] == 3
        assert out["summary"]["metric_count"] == 1
        assert out["summary"]["evidence_type_counts"]["technology"] == 3

    def test_groups_preserve_provenance_files(self):
        items = [
            _tech_obs("Django", "import_pattern", "core/models.py", "import django"),
            _tech_obs("Django", "import_pattern", "core/views.py", "import django"),
            _tech_obs("Django", "import_pattern", "api/views.py", "import django"),
        ]
        out = audit.audit_evidence(_evidence_doc(items=items))
        tech = next(g for g in out["groups"] if g["type"] == "technology")
        files = {f for f in tech["source_files"]["listed"]}
        assert "core/models.py" in files
        assert "core/views.py" in files
        assert "api/views.py" in files

    def test_examples_capped_at_three(self):
        items = [
            _tech_obs("Django", "import_pattern", f"f{i}.py", "import django")
            for i in range(10)
        ]
        out = audit.audit_evidence(_evidence_doc(items=items))
        tech = next(g for g in out["groups"] if g["type"] == "technology")
        assert len(tech["examples"]) == 3


# ─── B. malformed JSON handling (CLI) ─────────────────────────────────────


class TestCLI:
    def test_missing_file_returns_nonzero(self, tmp_path, capsys):
        code = audit.main([str(tmp_path / "nope.json")])
        assert code == 2

    def test_malformed_json_returns_nonzero(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not json", encoding="utf-8")
        code = audit.main([str(f)])
        assert code == 3

    def test_top_level_not_object_returns_nonzero(self, tmp_path):
        f = tmp_path / "list.json"
        f.write_text("[]", encoding="utf-8")
        code = audit.main([str(f)])
        assert code == 4

    def test_cli_writes_contract_input(self, tmp_path):
        f = tmp_path / "evidence.json"
        f.write_text(json.dumps(_evidence_doc()), encoding="utf-8")
        code = audit.main([str(f), "--markdown", str(tmp_path / "report.md")])
        assert code == 0
        out = tmp_path / "evidence-contract-input.json"
        assert out.exists()
        report = tmp_path / "report.md"
        assert report.exists()
        # And the output is valid JSON.
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["header"]["schema"] == audit.AUDIT_SCHEMA


# ─── C. empty evidence ────────────────────────────────────────────────────


class TestEmptyEvidence:
    def test_empty_evidence_array(self):
        out = audit.audit_evidence(_evidence_doc(items=[]))
        assert out["summary"]["evidence_count"] == 0
        assert out["groups"] == []
        assert out["duplication"]["exact_duplicate_groups"] == []
        assert out["duplication"]["near_duplicate_groups"] == []

    def test_empty_metrics_and_warnings(self):
        out = audit.audit_evidence(
            _evidence_doc(items=[], metrics=[], warnings=[])
        )
        assert out["metrics"]["total"] == 0
        assert out["warnings"]["total"] == 0


# ─── D. unknown evidence type ─────────────────────────────────────────────


class TestUnknownType:
    def test_unknown_type_does_not_crash(self):
        items = [
            {"id": "E-1", "type": "spectral_analysis", "subject": "x",
             "value": 1, "source": {"file": "x.py"}},
        ]
        out = audit.audit_evidence(_evidence_doc(items=items))
        assert out["summary"]["unknown_type_count"] == 1
        # Group is still emitted; consumer can decide what it is.
        spec = next(g for g in out["groups"] if g["type"] == "spectral_analysis")
        assert spec["count"] == 1


# ─── E. grouping ──────────────────────────────────────────────────────────


class TestGrouping:
    def test_groups_partition_by_type(self):
        items = [
            _tech_obs("Django", "import_pattern", "a.py", "import django"),
            {"id": "E-2", "type": "git", "subject": "current_branch",
             "value": "main", "source": {"method": "git"}},
            {"id": "E-3", "type": "git", "subject": "total_commits",
             "value": 10, "source": {"method": "git"}},
        ]
        out = audit.audit_evidence(_evidence_doc(items=items))
        type_to_count = {g["type"]: g["count"] for g in out["groups"]}
        assert type_to_count["technology"] == 1
        assert type_to_count["git"] == 2

    def test_subgroups_preserved_with_multiple_files(self):
        items = [
            _tech_obs("Django", "import_pattern", f"f{i}.py", "import django")
            for i in range(5)
        ]
        out = audit.audit_evidence(_evidence_doc(items=items))
        tech = next(g for g in out["groups"] if g["type"] == "technology")
        sg = tech["sub_groups_only_when_dense"]
        assert len(sg) == 1
        assert sg[0]["subject"] == "Django"
        assert sg[0]["count"] == 5
        assert sg[0]["source_files"]["count"] == 5


# ─── F. determinism ──────────────────────────────────────────────────────


class TestDeterminism:
    def test_two_runs_produce_identical_output(self, tmp_path):
        items = [
            _tech_obs("Django", "import_pattern", f"f{i}.py", "import django")
            for i in range(7)
        ] + [
            _tech_obs("Celery", "import_pattern", "tasks.py", "import celery"),
        ]
        doc = _evidence_doc(items=items)
        out1 = audit.audit_evidence(doc)
        out2 = audit.audit_evidence(doc)
        s1 = json.dumps(out1, sort_keys=True)
        s2 = json.dumps(out2, sort_keys=True)
        assert s1 == s2

    def test_idempotent_cli_with_explicit_source_timestamp(self, tmp_path):
        """Same input source -> same analyzed_at -> CLI output is deterministic."""
        f = tmp_path / "evidence.json"
        f.write_text(
            json.dumps(_evidence_doc(project={
                "name": "demo", "analyzed_at": "2026-01-01T00:00:00Z"
            })),
            encoding="utf-8",
        )
        out1 = tmp_path / "out1.json"
        out2 = tmp_path / "out2.json"
        code1 = audit.main([str(f), "--out", str(out1)])
        code2 = audit.main([str(f), "--out", str(out2)])
        assert code1 == 0
        assert code2 == 0
        # Both runs embed the source's analyzed_at as generated_at, so the
        # JSON is byte-identical.
        assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8")

    def test_explicit_generated_at_overrides(self):
        doc = _evidence_doc()
        a = audit.audit_evidence(doc, generated_at="2026-01-01T00:00:00Z")
        b = audit.audit_evidence(doc, generated_at="2026-01-01T00:00:00Z")
        assert a["header"]["generated_at"] == "2026-01-01T00:00:00Z"
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_falls_back_to_project_analyzed_at(self):
        doc = _evidence_doc(project={"name": "demo", "analyzed_at": "FIXED"})
        a = audit.audit_evidence(doc)
        b = audit.audit_evidence(doc)
        assert a["header"]["generated_at"] == "FIXED"
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ─── G. provenance preservation ──────────────────────────────────────────


class TestProvenance:
    def test_provenance_keys_preserved(self):
        items = [
            {
                "id": "E-1",
                "type": "technology",
                "subject": "Django",
                "value": "import django.db",
                "source": {
                    "file": "core/models.py",
                    "method": "regex_import_scan",
                    "pattern": "import django",
                    "line": 3,
                    "section": "imports",
                },
                "signal_type": "import_pattern",
            },
        ]
        out = audit.audit_evidence(_evidence_doc(items=items))
        tech = next(g for g in out["groups"] if g["type"] == "technology")
        # Examples should preserve full source.
        ex = tech["examples"][0]
        assert ex["source"]["file"] == "core/models.py"
        assert ex["source"]["line"] == 3
        assert ex["source"]["section"] == "imports"


# ─── H. duplicate detection ──────────────────────────────────────────────


class TestDuplication:
    def test_exact_duplicates_detected(self):
        items = [
            _tech_obs("Django", "dependency_declaration",
                      "requirements.txt", "django", detail="Django==5.0"),
            _tech_obs("Django", "dependency_declaration",
                      "requirements.txt", "django", detail="Django==5.0"),
        ]
        out = audit.audit_evidence(_evidence_doc(items=items))
        assert len(out["duplication"]["exact_duplicate_groups"]) == 1
        assert out["duplication"]["exact_duplicate_groups"][0]["occurrences"] == 2

    def test_near_duplicates_detected_when_value_differs(self):
        items = [
            _tech_obs("WhiteNoise", "dependency_declaration",
                      "requirements.txt", "whitenoise", detail="whitenoise"),
            _tech_obs("WhiteNoise", "dependency_declaration",
                      "requirements.txt", "whitenoise",
                      detail="whitenoise==6.8.2"),
        ]
        out = audit.audit_evidence(_evidence_doc(items=items))
        # Different values → not exact duplicates.
        assert out["duplication"]["exact_duplicate_groups"] == []
        # Same type/subject/file → near duplicate.
        assert len(out["duplication"]["near_duplicate_groups"]) == 1
        ng = out["duplication"]["near_duplicate_groups"][0]
        assert ng["occurrences"] == 2
        assert ng["source_file"] == "requirements.txt"

    def test_no_duplicates_when_items_distinct(self):
        items = [
            _tech_obs("Django", "import_pattern", "a.py", "import django"),
            _tech_obs("Celery", "import_pattern", "b.py", "import celery"),
        ]
        out = audit.audit_evidence(_evidence_doc(items=items))
        assert out["duplication"]["exact_duplicate_groups"] == []
        assert out["duplication"]["near_duplicate_groups"] == []


# ─── I. compactness / value shapes ───────────────────────────────────────


class TestCompactness:
    def test_audit_smaller_than_input(self, tmp_path):
        # Generate a moderately fat input.
        items = []
        for i in range(50):
            items.append(_tech_obs(
                "Django", "import_pattern", f"dir{i}/mod.py",
                "import django",
                detail=f"import django.{i}",
            ))
        doc = _evidence_doc(items=items)
        raw = json.dumps(doc, indent=2)
        audit_doc = audit.audit_evidence(doc)
        compact = json.dumps(audit_doc, indent=2)
        assert len(compact) < len(raw)

    def test_value_shapes_categorised(self):
        items = [
            _tech_obs("X", "import_pattern", "a.py", "import x", detail="abc"),
            {"id": "E-2", "type": "git", "subject": "commits",
             "value": 42, "source": {"method": "git"}},
            {"id": "E-3", "type": "git", "subject": "head_commit",
             "value": {"hash": "abc"}, "source": {"method": "git"}},
        ]
        out = audit.audit_evidence(_evidence_doc(items=items))
        tech = next(g for g in out["groups"] if g["type"] == "technology")
        git = next(g for g in out["groups"] if g["type"] == "git")
        assert "string" in tech["value_shapes"]
        assert "int" in git["value_shapes"]
        assert "dict[1]" in git["value_shapes"]