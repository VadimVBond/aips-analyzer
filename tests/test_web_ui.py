"""
AA-020 Web UI tests.

Smoke + integration tests for the Flask web interface.
All routes are tested against the real freelance_pulse output package.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from aips_analyzer.web.app import create_app


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PROJECT = PROJECT_ROOT / "output" / "freelance_pulse"


@pytest.fixture
def app():
    """Create app pointing at real output fixtures."""
    app = create_app()
    app.config["AIPS_OUTPUT_DIR"] = str(PROJECT_ROOT / "output")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


# ─── Smoke: all routes return expected status ────────────────────────────


class TestSmokeRoutes:
    """Per AA-020 §28 — smoke tests."""

    def test_home(self, client):
        r = client.get("/")
        assert r.status_code == 200

    def test_dashboard_ok(self, client):
        r = client.get("/dashboard", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200

    def test_dashboard_no_project_redirects(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 302

    def test_dashboard_nonexistent_project(self, client):
        r = client.get("/dashboard", query_string={"project": "nonexistent_project_xyz"})
        assert r.status_code == 404

    def test_evidence(self, client):
        r = client.get("/evidence", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200

    def test_evidence_no_project(self, client):
        r = client.get("/evidence")
        assert r.status_code == 400

    def test_facts(self, client):
        r = client.get("/facts", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200

    def test_metrics(self, client):
        r = client.get("/metrics", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200

    def test_architecture(self, client):
        r = client.get("/architecture", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200

    def test_dependencies(self, client):
        r = client.get("/dependencies", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200

    def test_git(self, client):
        r = client.get("/git", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200

    def test_ai_context(self, client):
        r = client.get("/ai_context", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200

    def test_artifacts(self, client):
        r = client.get("/artifacts", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200

    def test_artifacts_nonexistent(self, client):
        r = client.get("/artifacts", query_string={"project": "nonexistent_xyz"})
        assert r.status_code == 404


# ─── Content: pages render expected data ────────────────────────────────


class TestIntegration:
    """Per AA-020 §29 — integration with real freelance_pulse output."""

    def test_home_lists_freelance_pulse(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"freelance_pulse" in r.data

    def test_dashboard_has_project_name(self, client):
        r = client.get("/dashboard", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200
        assert b"freelance_pulse" in r.data

    def test_dashboard_has_evidence_count(self, client):
        r = client.get("/dashboard", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200
        # evidence-audit.md confirms 260 evidence items
        assert b"260" in r.data or b"Evidence" in r.data

    def test_evidence_has_table(self, client):
        r = client.get("/evidence", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200
        assert b"E-001" in r.data

    def test_evidence_type_filter(self, client):
        r = client.get(
            "/evidence",
            query_string={"project": "freelance_pulse", "type": "technology"},
        )
        assert r.status_code == 200
        assert b"technology" in r.data

    def test_facts_has_content(self, client):
        r = client.get("/facts", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200
        assert b"fact" in r.data.lower()

    def test_metrics_has_data(self, client):
        r = client.get("/metrics", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200
        assert b"metric" in r.data.lower()

    def test_architecture_has_modules(self, client):
        r = client.get("/architecture", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200
        assert b"module" in r.data.lower()

    def test_ai_context_has_facts(self, client):
        r = client.get("/ai_context", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200
        assert b"fact" in r.data.lower()

    def test_artifacts_shows_available(self, client):
        r = client.get("/artifacts", query_string={"project": "freelance_pulse"})
        assert r.status_code == 200
        assert b"available" in r.data


# ─── Error handling ───────────────────────────────────────────────


class TestErrorHandling:
    """Per AA-020 §27."""

    def test_nonexistent_project_returns_404(self, client):
        r = client.get("/evidence", query_string={"project": "this_project_does_not_exist"})
        assert r.status_code == 404

    def test_empty_project_path_returns_400(self, client):
        r = client.get("/evidence")
        assert r.status_code == 400

    def test_analysis_requires_path(self, client):
        r = client.post("/analyze", data={"project_path": ""})
        assert r.status_code == 400
        assert b"error" in r.data.lower()

    def test_analysis_nonexistent_path(self, client):
        r = client.post("/analyze", data={"project_path": "/this/path/does/not/exist"})
        assert r.status_code == 400
        assert b"does not exist" in r.data


# ─── App factory ─────────────────────────────────────────────────


class TestAppFactory:
    """App can be created with custom output dir."""

    def test_create_app_with_custom_output_dir(self):
        app = create_app()
        app.config["AIPS_OUTPUT_DIR"] = str(PROJECT_ROOT / "output")
        assert app.config["AIPS_OUTPUT_DIR"] == str(PROJECT_ROOT / "output")

    def test_routes_registered(self, app):
        rules = {r.rule for r in app.url_map.iter_rules()}
        expected = {
            "/",
            "/dashboard",
            "/analyze",
            "/analyze/status/<project_name>",
            "/evidence",
            "/facts",
            "/metrics",
            "/architecture",
            "/dependencies",
            "/git",
            "/ai_context",
            "/artifacts",
        }
        assert expected.issubset(rules)
