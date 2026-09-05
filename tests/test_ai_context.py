"""
AA-011 Tests — AI Context Renderer (aips-ai-context/v1).

Coverage:
- render_ai_context(): determinism, projection purity, schema.
- aggregate_v2_with_aa011(): 4 new fact_types (git, dependency_version).
- CLI --ai-context flag emits v1 schema.
- No Findings inside Facts (boundary).
- Raw evidence.json is not mutated.
- Backward compat with v1 and v2 schemas.
- Idempotency: re-running produces same output.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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
        "source": {"file": file, "method": signal_type, "pattern": pattern},
        "signal_type": signal_type,
    }


def _git_fact(subject, value, evidence_id="E-X"):
    return {
        "id": evidence_id,
        "type": "git",
        "subject": subject,
        "value": value,
        "source": {"method": "git_cli"},
    }


def _dep_fact(subject, value, evidence_id="E-X"):
    return {
        "id": evidence_id,
        "type": "dependency",
        "subject": subject,
        "value": value,
        "source": {"method": "file_parse"},
    }


def _arch_fact(subject, value, evidence_id="E-X"):
    return {
        "id": evidence_id,
        "type": "architecture",
        "subject": subject,
        "value": value,
        "source": {"method": "ast_import_graph"},
    }


def _evidence_doc(items, metrics=None, warnings=None):
    return {
        "schema": "aips-evidence/v1",
        "analyzer": {"name": "aips-analyzer", "version": "0.1.0"},
        "project": {
            "name": "test_project",
            "analyzed_at": "2026-01-01T00:00:00Z",
        },
        "evidence": items,
        "metrics": metrics or [],
        "warnings": warnings or [],
    }


# ─── AI Context Renderer: shape ────────────────────────────────────────


class TestRenderAiContextShape:
    def test_basic_shape(self):
        items = [
            _tech_obs("Django", "import_pattern", "a.py", "import django", "v"),
            _git_fact("current_branch", "main"),
            _dep_fact("django", {"file": "requirements.txt", "count": 1}),
        ]
        doc = _evidence_doc(items)
        agg = audit.aggregate_v2_with_aa011(doc)
        ctx = audit.render_ai_context(agg)
        assert ctx["header"]["schema"] == "aips-ai-context/v1"
        assert ctx["header"]["schema_version"] == "0.1.0"
        assert "summary" in ctx
        assert "facts" in ctx
        assert "metrics" in ctx
        assert "unknowns" in ctx
        assert "stable_groups_sample" in ctx
        assert "limits" in ctx
        assert "guidance_for_llm" in ctx

    def test_facts_contain_aa011_extensions(self):
        items = [
            _git_fact("current_branch", "main"),
            _git_fact("total_commits", 42),
            _dep_fact("django", "Django==5.2.10"),
        ]
        doc = _evidence_doc(items)
        agg = audit.aggregate_v2_with_aa011(doc)
        ctx = audit.render_ai_context(agg)
        fact_ids = {f["fact_id"] for f in ctx["facts"]}
        assert "git_repository_present[git]" in fact_ids
        assert "git_total_commits[git]" in fact_ids
        assert "git_current_branch[git]" in fact_ids
        assert "dependency_version[django]" in fact_ids

    def test_dependency_version_value(self):
        items = [_dep_fact("django", "Django==5.2.10")]
        doc = _evidence_doc(items)
        agg = audit.aggregate_v2_with_aa011(doc)
        ctx = audit.render_ai_context(agg)
        fv = [f for f in ctx["facts"] if f["fact_id"] == "dependency_version[django]"][
            0
        ]
        assert fv["value"] == "Django==5.2.10"
        assert "evidence_refs" in fv
        assert len(fv["evidence_refs"]) >= 1

    def test_git_total_commits_value(self):
        items = [_git_fact("total_commits", 100)]
        doc = _evidence_doc(items)
        agg = audit.aggregate_v2_with_aa011(doc)
        ctx = audit.render_ai_context(agg)
        fv = [f for f in ctx["facts"] if f["fact_id"] == "git_total_commits[git]"][0]
        assert fv["value"] == 100
        assert "evidence_refs" in fv


# ─── AI Context Renderer: determinism ───────────────────────────────


class TestRenderAiContextDeterminism:
    def test_same_input_same_output(self):
        items = [
            _tech_obs("Django", "import_pattern", "a.py", "import django", "v"),
            _git_fact("current_branch", "main"),
            _dep_fact("django", "Django==5.2.10"),
        ]
        doc = _evidence_doc(items)
        agg1 = audit.aggregate_v2_with_aa011(doc)
        agg2 = audit.aggregate_v2_with_aa011(doc)
        ctx1 = audit.render_ai_context(agg1)
        ctx2 = audit.render_ai_context(agg2)
        s1 = json.dumps(ctx1, sort_keys=True, ensure_ascii=False)
        s2 = json.dumps(ctx2, sort_keys=True, ensure_ascii=False)
        assert s1 == s2

    def test_reordered_input_same_output(self):
        items_a = [
            _tech_obs("Django", "import_pattern", "a.py", "import django", "v"),
            _git_fact("current_branch", "main"),
            _dep_fact("redis", "redis>=5.0"),
        ]
        items_b = list(reversed(items_a))
        agg_a = audit.aggregate_v2_with_aa011(_evidence_doc(items_a))
        agg_b = audit.aggregate_v2_with_aa011(_evidence_doc(items_b))
        ctx_a = audit.render_ai_context(agg_a)
        ctx_b = audit.render_ai_context(agg_b)
        s_a = json.dumps(ctx_a, sort_keys=True, ensure_ascii=False)
        s_b = json.dumps(ctx_b, sort_keys=True, ensure_ascii=False)
        assert s_a == s_b


# ─── AI Context Renderer: projection purity ──────────────────────────


class TestRenderAiContextPurity:
    def test_no_findings_in_facts(self):
        """AA-011 §7: Facts must NOT contain severity/risk/recommendation."""
        items = [
            _tech_obs("Django", "import_pattern", "a.py", "import django", "v"),
        ]
        doc = _evidence_doc(items)
        agg = audit.aggregate_v2_with_aa011(doc)
        ctx = audit.render_ai_context(agg)
        forbidden_keys = {
            "severity",
            "risk",
            "recommendation",
            "business_impact",
            "recovery_priority",
            "is_old",
            "is_dangerous",
            "is_bad",
        }
        for f in ctx["facts"]:
            for k in f.keys():
                assert k not in forbidden_keys, (
                    f"Fact {f.get('fact_id')} has forbidden key {k!r}"
                )

    def test_does_not_mutate_input_aggregated(self):
        items = [
            _tech_obs("Django", "import_pattern", "a.py", "import django", "v"),
            _git_fact("current_branch", "main"),
        ]
        doc = _evidence_doc(items)
        agg = audit.aggregate_v2_with_aa011(doc)
        # Capture snapshot before rendering.
        snapshot = json.dumps(agg, sort_keys=True, ensure_ascii=False)
        _ = audit.render_ai_context(agg)
        after = json.dumps(agg, sort_keys=True, ensure_ascii=False)
        assert snapshot == after, "render_ai_context must not mutate input"

    def test_does_not_invent_evidence(self):
        """Unknowns must be preserved verbatim, not silently dropped."""
        items = [
            {
                "id": "E-1",
                "type": "exotic_analysis",
                "subject": "x",
                "value": 1,
                "source": {"method": "weird"},
            },
        ]
        doc = _evidence_doc(items)
        agg = audit.aggregate_v2_with_aa011(doc)
        ctx = audit.render_ai_context(agg)
        # The unknown item must appear in unknowns[].
        assert any(u.get("type") == "exotic_analysis" for u in ctx["unknowns"]), (
            "Unknowns must not be silently dropped"
        )

    def test_git_not_present_marks_false_not_unknown(self):
        """When no git evidence exists, git_repository_present[git] is False
        with a `note` field explaining it is a projection."""
        items = [
            _tech_obs("Django", "import_pattern", "a.py", "import django", "v"),
        ]
        doc = _evidence_doc(items)
        agg = audit.aggregate_v2_with_aa011(doc)
        ctx = audit.render_ai_context(agg)
        f = [x for x in ctx["facts"] if x["fact_id"] == "git_repository_present[git]"][
            0
        ]
        assert f["value"] is False
        # Note must explain this is a projection.
        assert "projection" in f.get("note", "").lower()


# ─── AI Context Renderer: input validation ──────────────────────────


class TestRenderAiContextInputValidation:
    def test_missing_header_raises(self):
        with pytest.raises(ValueError, match="header"):
            audit.render_ai_context({})

    def test_missing_stable_groups_raises(self):
        with pytest.raises(ValueError, match="stable_groups"):
            audit.render_ai_context({"header": {}})

    def test_wrong_type_raises(self):
        with pytest.raises(TypeError):
            audit.render_ai_context("not a dict")


# ─── aggregate_v2_with_aa011: idempotency ───────────────────────────


class TestAggregateV2WithAA011:
    def test_idempotent(self):
        """AA-011 extension adds 4 new fact_types when applicable.

        For input with current_branch evidence, AA-011 should add:
        - git_repository_present[git] (always when git evidence present)
        - git_current_branch[git] (when current_branch evidence present)
        Note: git_total_commits and dependency_version depend on
        the specific evidence types present.
        """
        items = [
            _tech_obs("Django", "import_pattern", "a.py", "import django", "v"),
            _git_fact("current_branch", "main"),
        ]
        doc = _evidence_doc(items)
        agg1 = audit.aggregate_v2_with_aa011(doc)
        agg2 = audit.aggregate_v2_with_aa011(doc)
        # Running twice must not duplicate AA-011 facts.
        # Count fact_ids.
        ids1 = sorted(
            f["fact_id"]
            for f in agg1["facts"]
            if any(f["fact_id"].startswith(p) for p in ("git_", "dependency_version"))
        )
        ids2 = sorted(
            f["fact_id"]
            for f in agg2["facts"]
            if any(f["fact_id"].startswith(p) for p in ("git_", "dependency_version"))
        )
        assert ids1 == ids2, f"AA-011 facts not idempotent: {ids1} != {ids2}"
        # Specifically: should have git_repository_present + git_current_branch.
        assert "git_repository_present[git]" in ids1
        assert "git_current_branch[git]" in ids1

    def test_existing_aa011_facts_not_duplicated(self):
        items = [_git_fact("current_branch", "main")]
        doc = _evidence_doc(items)
        agg = audit.aggregate_v2_with_aa011(doc)
        # Run twice — should still have exactly one git_repository_present.
        agg = audit.aggregate_v2_with_aa011(agg)
        count = sum(
            1 for f in agg["facts"] if f["fact_id"] == "git_repository_present[git]"
        )
        assert count == 1


# ─── CLI --ai-context ───────────────────────────────────────────────


class TestCLIAiContext:
    def test_help_shows_flag(self):
        result = subprocess.run(
            [sys.executable, str(AUDIT_PATH), "--help"],
            capture_output=True,
            text=True,
        )
        assert "--ai-context" in result.stdout

    def test_ai_context_flag_emits_v1(self, tmp_path):
        src = tmp_path / "evidence.json"
        doc = _evidence_doc(
            [
                _tech_obs("Django", "import_pattern", "a.py", "import django", "v"),
                _git_fact("current_branch", "main"),
            ]
        )
        src.write_text(json.dumps(doc), encoding="utf-8")
        out = tmp_path / "out.json"
        result = subprocess.run(
            [
                sys.executable,
                str(AUDIT_PATH),
                str(src),
                "--out",
                str(out),
                "--ai-context",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["header"]["schema"] == "aips-ai-context/v1"

    def test_no_flag_emits_v1_audit(self, tmp_path):
        """Backward compat: without flag, v1 audit is emitted."""
        src = tmp_path / "evidence.json"
        doc = _evidence_doc(
            [
                _tech_obs("Django", "import_pattern", "a.py", "import django", "v"),
            ]
        )
        src.write_text(json.dumps(doc), encoding="utf-8")
        out = tmp_path / "out.json"
        result = subprocess.run(
            [sys.executable, str(AUDIT_PATH), str(src), "--out", str(out)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["header"]["schema"] == audit.AUDIT_SCHEMA


# ─── Integration: freelance_pulse real output ──────────────────────


class TestIntegrationFreelancePulse:
    """If freelance_pulse evidence exists, run on it."""

    @pytest.fixture
    def freelance_evidence(self):
        path = Path("output/freelance_pulse/evidence.json")
        if not path.exists():
            pytest.skip("freelance_pulse evidence not available")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_ai_context_size_substantial_reduction(self, freelance_evidence, tmp_path):
        agg = audit.aggregate_v2_with_aa011(freelance_evidence)
        ctx = audit.render_ai_context(agg)
        raw_size = len(json.dumps(freelance_evidence))
        ctx_size = len(json.dumps(ctx))
        # AI Context should be substantially smaller than raw evidence.
        assert ctx_size < raw_size, (
            f"AI Context ({ctx_size}) should be smaller than raw evidence ({raw_size})"
        )

    def test_ai_context_has_git_facts(self, freelance_evidence):
        agg = audit.aggregate_v2_with_aa011(freelance_evidence)
        ctx = audit.render_ai_context(agg)
        fact_ids = {f["fact_id"] for f in ctx["facts"]}
        assert "git_repository_present[git]" in fact_ids
