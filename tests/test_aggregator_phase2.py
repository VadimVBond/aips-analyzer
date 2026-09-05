"""
AA-008 Tests — Aggregator Phase 2 (stable_id + grouping + Facts).

Tests:
- stable_id algorithm: deterministic, value-drift-safe, path-drift-safe,
  ordering-insensitive.
- display_key: reflects path/method for debugging.
- grouping: same stable_id collapses observations; value drift keeps
  same group but different value.
- Facts: technology_present, technology_version, dependency_declared,
  architecture_cycles_present, architecture_parse_errors_present.
- canonical_metrics: project repository_metric evidence, deduplicate
  with metrics[].
- unknown[]: items with unresolvable types.
- deterministic: same input -> identical output, byte-for-byte.
- backward compatibility: audit_evidence() unchanged.
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
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


audit = _load_audit_module()


# ─── Helpers ───────────────────────────────────────────────────────────


def _tech_obs(tech, signal_type, file, pattern, value, evidence_id="E-X"):
    return {
        "id": evidence_id,
        "type": "technology",
        "subject": tech,
        "value": value,
        "source": {
            "file": file,
            "method": signal_type,
            "pattern": pattern,
        },
        "signal_type": signal_type,
    }


def _repo_metric(metric_name, value, evidence_id="E-X", notes=None):
    return {
        "id": evidence_id,
        "type": "repository_metric",
        "subject": metric_name,
        "value": value,
        "source": {"method": "filesystem"},
        "notes": notes,
    }


def _git_fact(subject, value, evidence_id="E-X"):
    return {
        "id": evidence_id,
        "type": "git",
        "subject": subject,
        "value": value,
        "source": {"method": "git_cli"},
    }


def _arch_fact(subject, value, evidence_id="E-X"):
    return {
        "id": evidence_id,
        "type": "architecture",
        "subject": subject,
        "value": value,
        "source": {"method": "ast_import_graph"},
    }


def _dep_fact(subject, value, evidence_id="E-X"):
    return {
        "id": evidence_id,
        "type": "dependency",
        "subject": subject,
        "value": value,
        "source": {"method": "file_parse"},
    }


def _evidence_doc(items, metrics=None):
    return {
        "schema": "aips-evidence/v1",
        "analyzer": {"name": "aips-analyzer", "version": "0.1.0"},
        "project": {
            "name": "test_project",
            "analyzed_at": "2026-01-01T00:00:00Z",
        },
        "evidence": items,
        "metrics": metrics or [],
        "warnings": [],
    }


# ─── stable_id algorithm ─────────────────────────────────────────────


class TestStableId:
    def test_basic_technology(self):
        item = _tech_obs("Django", "import_pattern", "core/models.py",
                         "import django", "import django.db")
        sid = audit.stable_id_for_evidence(item)
        assert sid.startswith("technology:Django:")
        assert "import_pattern" in sid or "regex_import_scan" in sid

    def test_does_not_include_value(self):
        a = _tech_obs("Django", "import_pattern", "core/models.py",
                      "import django", "import django.db")
        b = _tech_obs("Django", "import_pattern", "core/models.py",
                      "import django", "import django.contrib.auth")
        assert audit.stable_id_for_evidence(a) == audit.stable_id_for_evidence(b), (
            "value drift must not change stable_id")

    def test_does_not_include_file_path(self):
        a = _tech_obs("Django", "import_pattern", "core/models.py",
                      "import django", "import django.db")
        b = _tech_obs("Django", "import_pattern", "core/django_manage.py",
                      "import django", "import django.db")
        assert audit.stable_id_for_evidence(a) == audit.stable_id_for_evidence(b), (
            "file rename must not change stable_id")

    def test_does_not_include_evidence_id(self):
        a = _tech_obs("Django", "import_pattern", "a.py", "import django",
                      "v", evidence_id="E-001")
        b = _tech_obs("Django", "import_pattern", "a.py", "import django",
                      "v", evidence_id="E-227")
        assert audit.stable_id_for_evidence(a) == audit.stable_id_for_evidence(b)

    def test_does_not_include_notes_or_timestamps(self):
        a = _tech_obs("Django", "import_pattern", "a.py", "import django", "v")
        a["notes"] = "analyzer version 0.1.0"
        a["first_seen"] = "2026-09-04T00:00:00Z"
        b = _tech_obs("Django", "import_pattern", "a.py", "import django", "v")
        assert audit.stable_id_for_evidence(a) == audit.stable_id_for_evidence(b)

    def test_method_change_changes_stable_id(self):
        a = _tech_obs("Django", "regex_import_scan", "a.py",
                      "import django", "v")
        b = _tech_obs("Django", "ast_import_scan", "a.py",
                      "import django", "v")
        assert audit.stable_id_for_evidence(a) != audit.stable_id_for_evidence(b), (
            "detector change is contract-visible (ADR-001)")

    def test_pattern_canonicalization(self):
        a = _tech_obs("Django", "import_pattern", "a.py",
                      "  Import   Django  ", "v")
        b = _tech_obs("Django", "import_pattern", "a.py",
                      "import django", "v")
        assert audit.stable_id_for_evidence(a) == audit.stable_id_for_evidence(b), (
            "pattern canonicalization: strip + lowercase + collapse ws")

    def test_different_subjects_different_ids(self):
        a = _tech_obs("Django", "import_pattern", "a.py",
                      "import django", "v")
        b = _tech_obs("Flask", "import_pattern", "a.py",
                      "import flask", "v")
        assert audit.stable_id_for_evidence(a) != audit.stable_id_for_evidence(b)


class TestDisplayKey:
    def test_includes_file(self):
        item = _tech_obs("Django", "import_pattern", "core/models.py",
                         "import django", "v")
        dk = audit.display_key_for_evidence(item)
        assert "core/models.py" in dk

    def test_changes_with_file(self):
        a = _tech_obs("Django", "import_pattern", "a.py",
                      "import django", "v")
        b = _tech_obs("Django", "import_pattern", "b.py",
                      "import django", "v")
        assert audit.display_key_for_evidence(a) != \
            audit.display_key_for_evidence(b)

    def test_stable_id_unchanged_when_file_changes(self):
        a = _tech_obs("Django", "import_pattern", "a.py",
                      "import django", "v")
        b = _tech_obs("Django", "import_pattern", "b.py",
                      "import django", "v")
        assert audit.stable_id_for_evidence(a) == \
            audit.stable_id_for_evidence(b)
        assert audit.display_key_for_evidence(a) != \
            audit.display_key_for_evidence(b)


# ─── Grouping ──────────────────────────────────────────────────────────


class TestGrouping:
    def test_same_stable_id_collapses(self):
        items = [
            _tech_obs("Django", "import_pattern", f"f{i}.py",
                      "import django", f"import django.module{i}")
            for i in range(5)
        ]
        out = audit.aggregate_v2(_evidence_doc(items))
        # All 5 should collapse into 1 group with 5 observations.
        django_groups = [g for g in out["stable_groups"]
                         if g["subject"] == "Django"]
        assert len(django_groups) == 1
        assert django_groups[0]["observation_count"] == 5

    def test_value_drift_keeps_group(self):
        a = _tech_obs("Django", "import_pattern", "a.py",
                      "import django", "5.2.10")
        b = _tech_obs("Django", "import_pattern", "b.py",
                      "import django", "5.2.11")
        out = audit.aggregate_v2(_evidence_doc([a, b]))
        django = [g for g in out["stable_groups"]
                  if g["subject"] == "Django"][0]
        # Same stable_id, group keeps both values.
        assert django["value_count"] == 2
        assert "5.2.10" in django["values"]
        assert "5.2.11" in django["values"]

    def test_ordering_does_not_change_output(self):
        items_a = [
            _tech_obs("Django", "import_pattern", "f0.py",
                      "import django", "v0"),
            _tech_obs("Celery", "import_pattern", "f1.py",
                      "import celery", "v1"),
            _tech_obs("Redis", "import_pattern", "f2.py",
                      "import redis", "v2"),
        ]
        items_b = list(reversed(items_a))
        out_a = audit.aggregate_v2(_evidence_doc(items_a))
        out_b = audit.aggregate_v2(_evidence_doc(items_b))
        # Same stable_groups list (sorted by stable_id).
        assert out_a["stable_groups"] == out_b["stable_groups"]

    def test_duplicate_observations_group(self):
        a1 = _tech_obs("Django", "import_pattern", "a.py",
                       "import django", "v")
        a2 = _tech_obs("Django", "import_pattern", "a.py",
                       "import django", "v")
        out = audit.aggregate_v2(_evidence_doc([a1, a2]))
        django = [g for g in out["stable_groups"]
                  if g["subject"] == "Django"][0]
        assert django["observation_count"] == 2
        # value_count should be 1 (same value deduplicated).
        assert django["value_count"] == 1


# ─── Facts ──────────────────────────────────────────────────────────────


class TestFacts:
    def test_technology_present_fact(self):
        items = [
            _tech_obs("Django", "import_pattern", "a.py",
                      "import django", "v"),
            _tech_obs("Celery", "import_pattern", "b.py",
                      "import celery", "v"),
        ]
        out = audit.aggregate_v2(_evidence_doc(items))
        fact_ids = {f["fact_id"] for f in out["facts"]}
        assert "technology_present[Django]" in fact_ids
        assert "technology_present[Celery]" in fact_ids

    def test_technology_version_fact(self):
        items = [
            _tech_obs("Django", "dependency_declaration",
                      "requirements.txt", "django",
                      "Django==5.2.10"),
        ]
        out = audit.aggregate_v2(_evidence_doc(items))
        version_facts = [f for f in out["facts"]
                         if f["fact_type"] == "technology_version"]
        assert len(version_facts) >= 1
        # Value should contain "Django==5.2.10"
        django_version = [f for f in version_facts
                          if f["subject"] == "Django"]
        assert len(django_version) == 1
        assert "5.2.10" in django_version[0]["value"]

    def test_dependency_declared_fact(self):
        items = [
            _dep_fact("django", {"file": "requirements.txt", "count": 1}),
        ]
        out = audit.aggregate_v2(_evidence_doc(items))
        fact_ids = {f["fact_id"] for f in out["facts"]}
        assert "dependency_declared[django]" in fact_ids

    def test_architecture_cycles_present(self):
        items = [
            _arch_fact("cyclic_dependencies", {"count": 1, "cycles": []}),
        ]
        out = audit.aggregate_v2(_evidence_doc(items))
        fact_ids = {f["fact_id"] for f in out["facts"]}
        assert "architecture_cycles_present" in fact_ids

    def test_architecture_parse_errors_present(self):
        items = [
            _arch_fact("parse_errors", [{"file": "x.py", "error": "..."}]),
        ]
        out = audit.aggregate_v2(_evidence_doc(items))
        fact_ids = {f["fact_id"] for f in out["facts"]}
        assert "architecture_parse_errors_present" in fact_ids

    def test_facts_never_severity(self):
        """ADR-001: Aggregator must NOT emit severity / risk."""
        items = [
            _arch_fact("cyclic_dependencies", {"count": 1}),
        ]
        out = audit.aggregate_v2(_evidence_doc(items))
        for f in out["facts"]:
            assert "severity" not in f
            assert "risk" not in f
            assert "recommendation" not in f


# ─── canonical_metrics ─────────────────────────────────────────────────


class TestCanonicalMetrics:
    def test_metrics_section_projects_to_canonical(self):
        items = []
        metrics = [
            {"name": "discovery.python_files", "value": 209},
        ]
        out = audit.aggregate_v2(_evidence_doc(items, metrics))
        names = [m["name"] for m in out["canonical_metrics"]]
        assert "discovery.python_files" in names
        m = next(m for m in out["canonical_metrics"]
                 if m["name"] == "discovery.python_files")
        assert m["unit"] == "files"
        assert m["value"] == 209

    def test_repository_metric_evidence_links_to_existing(self):
        items = [
            _repo_metric("python_files", 209, evidence_id="E-001",
                          notes="from filesystem"),
        ]
        metrics = [{"name": "discovery.python_files", "value": 209}]
        out = audit.aggregate_v2(_evidence_doc(items, metrics))
        m = next(m for m in out["canonical_metrics"]
                 if m["name"] == "discovery.python_files")
        # Should have evidence_refs with the stable_id of the
        # repository_metric item.
        assert any("repository.python_files" in ref or
                   "repository.metric.filesystem" in ref
                   for ref in m["evidence_refs"])

    def test_repository_metric_creates_new_if_no_match(self):
        items = [
            _repo_metric("orphan_metric", 42, evidence_id="E-099"),
        ]
        out = audit.aggregate_v2(_evidence_doc(items))
        names = [m["name"] for m in out["canonical_metrics"]]
        assert "repository.orphan_metric" in names
        m = next(m for m in out["canonical_metrics"]
                 if m["name"] == "repository.orphan_metric")
        assert m["value"] == 42
        # Notes preserved per ADR-001.
        assert m["notes"] is None  # not set in this test

    def test_no_repository_metric_evidence_emitted_in_canonical(self):
        """Per ADR-001: repository_metric as evidence is deprecated."""
        items = [_repo_metric("python_files", 209)]
        out = audit.aggregate_v2(_evidence_doc(items))
        # The output has no "type=repository_metric" as evidence item.
        assert "evidence" not in out
        # canonical_metrics has the metric but not as a duplicate.
        assert isinstance(out["canonical_metrics"], list)


# ─── unknown[] ──────────────────────────────────────────────────────────


class TestUnknown:
    def test_unknown_type_goes_to_unknown(self):
        items = [
            {"id": "E-X", "type": "spectral_analysis",
             "subject": "x", "value": 1,
             "source": {"method": "fft"}},
        ]
        out = audit.aggregate_v2(_evidence_doc(items))
        assert len(out["unknown"]) == 1
        assert out["unknown"][0]["type"] == "spectral_analysis"
        assert "reason" in out["unknown"][0]

    def test_known_types_not_in_unknown(self):
        items = [
            _tech_obs("Django", "import_pattern", "a.py",
                      "import django", "v"),
        ]
        out = audit.aggregate_v2(_evidence_doc(items))
        assert out["unknown"] == []


# ─── Determinism ───────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_input_same_output(self):
        items = [
            _tech_obs("Django", "import_pattern", "a.py",
                      "import django", "v"),
            _repo_metric("python_files", 209),
            _git_fact("current_branch", "main"),
        ]
        doc = _evidence_doc(items)
        out1 = audit.aggregate_v2(doc)
        out2 = audit.aggregate_v2(doc)
        s1 = json.dumps(out1, sort_keys=True, ensure_ascii=False)
        s2 = json.dumps(out2, sort_keys=True, ensure_ascii=False)
        assert s1 == s2, "two runs must produce byte-identical output"

    def test_reordered_input_same_output(self):
        items_a = [
            _tech_obs("Django", "import_pattern", "a.py",
                      "import django", "v"),
            _tech_obs("Celery", "import_pattern", "b.py",
                      "import celery", "v"),
            _tech_obs("Redis", "import_pattern", "c.py",
                      "import redis", "v"),
        ]
        items_b = list(reversed(items_a))
        out_a = audit.aggregate_v2(_evidence_doc(items_a))
        out_b = audit.aggregate_v2(_evidence_doc(items_b))
        s1 = json.dumps(out_a, sort_keys=True, ensure_ascii=False)
        s2 = json.dumps(out_b, sort_keys=True, ensure_ascii=False)
        assert s1 == s2

    def test_stable_id_does_not_depend_on_position(self):
        items = [
            _tech_obs("Django", "import_pattern", "a.py",
                      "import django", "v", evidence_id="E-001"),
            _tech_obs("Django", "import_pattern", "a.py",
                      "import django", "v", evidence_id="E-002"),
        ]
        out = audit.aggregate_v2(_evidence_doc(items))
        # Both items have same stable_id; they collapse to one group.
        groups = [g for g in out["stable_groups"]
                  if g["subject"] == "Django"]
        assert len(groups) == 1
        assert groups[0]["observation_count"] == 2


# ─── CLI flag ──────────────────────────────────────────────────────────


class TestCLIAggregated:
    def test_help_shows_aggregated_flag(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, str(AUDIT_PATH), "--help"],
            capture_output=True, text=True,
        )
        assert "--aggregated" in result.stdout

    def test_aggregated_flag_emits_v2(self, tmp_path):
        import subprocess
        src = tmp_path / "evidence.json"
        doc = _evidence_doc([_tech_obs("Django", "import_pattern",
                                       "a.py", "import django", "v")])
        src.write_text(json.dumps(doc), encoding="utf-8")
        out = tmp_path / "out.json"
        result = subprocess.run(
            [sys.executable, str(AUDIT_PATH), str(src),
             "--out", str(out), "--aggregated"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["header"]["schema"] == "aips-evidence-audit/v2"
        assert data["header"]["phase"] == 2
        assert "stable_groups" in data

    def test_no_flag_emits_v1(self, tmp_path):
        import subprocess
        src = tmp_path / "evidence.json"
        doc = _evidence_doc([_tech_obs("Django", "import_pattern",
                                       "a.py", "import django", "v")])
        src.write_text(json.dumps(doc), encoding="utf-8")
        out = tmp_path / "out.json"
        result = subprocess.run(
            [sys.executable, str(AUDIT_PATH), str(src), "--out", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["header"]["schema"] == audit.AUDIT_SCHEMA
        # v1 audit has 'groups' not 'stable_groups'.
        assert "groups" in data
        assert "stable_groups" not in data


import sys  # needed for TestCLIAggregated