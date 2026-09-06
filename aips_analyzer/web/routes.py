"""
AIPS Analyzer Web UI — Routes.

All routes read from the output package (output/<project>/)
produced by the CLI analyzer. No database; no new analysis code.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from pathlib import Path
from typing import Any

from flask import (
    Blueprint,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

logger = logging.getLogger(__name__)

bp = Blueprint("ui", __name__)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_output_dir():
    from flask import current_app

    return Path(current_app.config.get("AIPS_OUTPUT_DIR", "output"))


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _load_artifact(project: str, filename: str) -> dict[str, Any] | None:
    path = _get_output_dir() / project / filename
    return _load_json(path)


def _project_exists(project: str) -> bool:
    return (_get_output_dir() / project).is_dir()


def _get_artifact_paths(project: str) -> dict[str, Path]:
    """Return paths for all known artifacts, with existence flag."""
    base = _get_output_dir() / project
    names = [
        "evidence.json",
        "evidence-aggregated.json",
        "evidence-ai-context.json",
        "evidence-audit.md",
        "manifest.json",
    ]
    return {n: base / n for n in names}


# ── Nav items ────────────────────────────────────────────────────────────────

NAV_ITEMS = [
    ("dashboard", "Overview", "chart-bar"),
    ("evidence", "Evidence", "list"),
    ("facts", "Facts", "check-circle"),
    ("metrics", "Metrics", "gauge"),
    ("architecture", "Architecture", "layers"),
    ("dependencies", "Dependencies", "package"),
    ("git", "Git", "git-branch"),
    ("ai_context", "AI Context", "cpu"),
    ("artifacts", "Artifacts", "archive"),
]


# ── Context processor ────────────────────────────────────────────────────────


@bp.context_processor
def inject_nav():
    def is_active(name: str) -> bool:
        # Determine active from endpoint or project in view args
        endpoint = request.endpoint or ""
        if name == "dashboard" and endpoint in ("ui.home", "ui.dashboard"):
            return True
        return endpoint == f"ui.{name}"

    return dict(
        nav_items=NAV_ITEMS,
        is_active=is_active,
    )


# ── Home / Project Selection ─────────────────────────────────────────────────


@bp.route("/")
def home():
    """Home page: select a project to view."""
    output_dir = _get_output_dir()
    projects = []
    if output_dir.is_dir():
        for p in sorted(output_dir.iterdir(), key=lambda x: x.name.lower()):
            if p.is_dir() and (p / "evidence.json").exists():
                evidence = _load_json(p / "evidence.json")
                agg_path = p / "evidence-aggregated.json"
                agg = _load_json(agg_path)
                projects.append(
                    {
                        "name": p.name,
                        "analyzed_at": (
                            evidence.get("project", {}).get("analyzed_at", "—")
                            if evidence
                            else "—"
                        ),
                        "fact_count": (len(agg.get("facts", [])) if agg else "—"),
                        "metric_count": (
                            len(agg.get("canonical_metrics", [])) if agg else "—"
                        ),
                    }
                )
    return render_template("home.html", projects=projects)


@bp.route("/dashboard")
def dashboard():
    project = request.args.get("project", "")
    if not project:
        return redirect(url_for("ui.home"))

    if not _project_exists(project):
        abort(404, description=f"Project not found: {project}")

    evidence = _load_artifact(project, "evidence.json")
    agg = _load_artifact(project, "evidence-aggregated.json")
    manifest = _load_artifact(project, "manifest.json")

    if evidence is None:
        abort(404, description="evidence.json not found")

    proj_meta = evidence.get("project", {})
    discovery = evidence.get("discovery", {})
    repository = evidence.get("repository", {})
    git_data = evidence.get("git", {})
    arch = evidence.get("architecture", {})
    warnings = evidence.get("warnings", [])
    evidence_items = evidence.get("evidence", [])

    metrics_raw = evidence.get("metrics", [])

    # Top-level counts for dashboard cards
    card_data = {
        "files": discovery.get("total_files", 0),
        "python_files": discovery.get("python_files_count", 0),
        "test_files": discovery.get("test_files_count", 0),
        "total_loc": repository.get("total_lines", 0),
        "python_loc": repository.get("python_lines", 0),
        "modules": arch.get("total_modules", 0),
        "facts": len(agg.get("facts", [])) if agg else 0,
        "canonical_metrics": len(agg.get("canonical_metrics", [])) if agg else 0,
        "unknowns": len(agg.get("unknowns", [])) if agg else 0,
        "git_commits": git_data.get("commits_count", 0) if git_data else 0,
        "cycles": arch.get("cyclic_dependencies", {}).get("count", 0),
        "evidence_items": len(evidence_items),
        "warnings": len(warnings),
    }

    # Facts summary
    facts_summary = []
    if agg:
        for fact in agg.get("facts", [])[:20]:
            facts_summary.append(
                {
                    "fact_type": fact.get("fact_type", ""),
                    "subject": fact.get("subject", ""),
                    "value": fact.get("value"),
                }
            )

    return render_template(
        "dashboard.html",
        project=project,
        proj_meta=proj_meta,
        card_data=card_data,
        facts_summary=facts_summary,
        warnings=warnings,
        metrics_raw=metrics_raw[:10],
        git_data=git_data,
        artifact_paths=_get_artifact_paths(project),
    )


# ── Analysis trigger ──────────────────────────────────────────────────────────


@bp.route("/analyze", methods=["POST"])
def analyze():
    """Trigger analysis via the existing CLI pipeline."""
    project_path = request.form.get("project_path", "").strip()
    if not project_path:
        return jsonify({"error": "Project path is required"}), 400

    path = Path(project_path)
    if not path.exists():
        return jsonify({"error": f"Path does not exist: {project_path}"}), 400
    if not path.is_dir():
        return jsonify({"error": f"Not a directory: {project_path}"}), 400

    output_dir = _get_output_dir()

    # Run in background thread so we can stream status via SSE
    def _run():
        try:
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "aips_analyzer",
                    str(path),
                    "--output",
                    str(output_dir),
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            return result.returncode, result.stdout, result.stderr
        except Exception as exc:
            return 2, "", str(exc)

    thread = threading.Thread(target=lambda: _run())
    thread.start()

    return jsonify(
        {
            "status": "started",
            "project": path.name,
            "message": "Analysis started in background.",
        }
    )


@bp.route("/analyze/status/<project_name>")
def analyze_status(project_name: str):
    """Check if analysis for project_name has completed."""
    project = _get_output_dir() / project_name
    if (project / "evidence.json").exists():
        return jsonify({"status": "done", "project": project_name})
    return jsonify({"status": "running", "project": project_name})


# ── Evidence ─────────────────────────────────────────────────────────────────


@bp.route("/evidence")
def evidence():
    project = request.args.get("project", "")
    if not project or not _project_exists(project):
        abort(404 if project else 400, description="Project required")

    evidence_data = _load_artifact(project, "evidence.json")
    if evidence_data is None:
        abort(404, description="evidence.json not found")

    all_items = evidence_data.get("evidence", [])

    # Filter params
    type_filter = request.args.get("type", "")
    search = request.args.get("q", "").lower()

    filtered = all_items
    if type_filter:
        filtered = [e for e in filtered if e.get("type") == type_filter]
    if search:
        filtered = [
            e
            for e in filtered
            if search
            in (
                str(e.get("subject", ""))
                + str(e.get("value", ""))
                + str(e.get("id", ""))
            ).lower()
        ]

    types = sorted({e.get("type", "") for e in all_items})

    return render_template(
        "evidence.html",
        project=project,
        all_items=all_items,
        filtered_items=filtered,
        types=types,
        type_filter=type_filter,
        search=search,
        total_count=len(all_items),
        filtered_count=len(filtered),
    )


# ── Facts ────────────────────────────────────────────────────────────────────


@bp.route("/facts")
def facts():
    project = request.args.get("project", "")
    if not project or not _project_exists(project):
        abort(404 if project else 400, description="Project required")

    agg = _load_artifact(project, "evidence-aggregated.json")
    if agg is None:
        abort(404, description="evidence-aggregated.json not found")

    all_facts = agg.get("facts", [])
    unknowns = agg.get("unknowns", [])

    # Group facts by fact_type
    fact_types = sorted({f.get("fact_type", "") for f in all_facts})
    facts_by_type: dict[str, list[dict]] = {}
    for ft in fact_types:
        facts_by_type[ft] = [f for f in all_facts if f.get("fact_type") == ft]

    type_filter = request.args.get("type", "")
    if type_filter and type_filter in facts_by_type:
        display_facts = facts_by_type[type_filter]
    else:
        display_facts = all_facts

    return render_template(
        "facts.html",
        project=project,
        all_facts=all_facts,
        facts_by_type=facts_by_type,
        fact_types=fact_types,
        type_filter=type_filter,
        display_facts=display_facts,
        unknowns=unknowns,
        total_facts=len(all_facts),
        total_unknowns=len(unknowns),
    )


# ── Metrics ──────────────────────────────────────────────────────────────────


@bp.route("/metrics")
def metrics():
    project = request.args.get("project", "")
    if not project or not _project_exists(project):
        abort(404 if project else 400, description="Project required")

    agg = _load_artifact(project, "evidence-aggregated.json")
    evidence_data = _load_artifact(project, "evidence.json")

    metrics_list = []
    if agg:
        metrics_list = agg.get("canonical_metrics", [])
    if not metrics_list and evidence_data:
        metrics_list = evidence_data.get("metrics", [])

    # Group by top-level prefix
    grouped: dict[str, list[dict]] = {}
    for m in metrics_list:
        name: str = m.get("name", "")
        prefix, _, rest = name.partition(".")
        key = prefix or "general"
        grouped.setdefault(key, []).append(m)

    return render_template(
        "metrics.html",
        project=project,
        metrics_list=metrics_list,
        grouped=grouped,
        total=len(metrics_list),
    )


# ── Architecture ──────────────────────────────────────────────────────────────


@bp.route("/architecture")
def architecture():
    project = request.args.get("project", "")
    if not project or not _project_exists(project):
        abort(404 if project else 400, description="Project required")

    evidence_data = _load_artifact(project, "evidence.json")
    if evidence_data is None:
        abort(404, description="evidence.json not found")

    arch = evidence_data.get("architecture", {})
    modules = arch.get("modules", [])
    cyclic = arch.get("cyclic_dependencies", {})

    return render_template(
        "architecture.html",
        project=project,
        arch=arch,
        modules=modules,
        cyclic=cyclic,
        total_modules=len(modules),
    )


# ── Dependencies ─────────────────────────────────────────────────────────────


@bp.route("/dependencies")
def dependencies():
    project = request.args.get("project", "")
    if not project or not _project_exists(project):
        abort(404 if project else 400, description="Project required")

    evidence_data = _load_artifact(project, "evidence.json")
    if evidence_data is None:
        abort(404, description="evidence.json not found")

    deps = evidence_data.get("dependencies", {})

    return render_template(
        "dependencies.html",
        project=project,
        deps=deps,
    )


# ── Git ──────────────────────────────────────────────────────────────────────


@bp.route("/git")
def git():
    project = request.args.get("project", "")
    if not project or not _project_exists(project):
        abort(404 if project else 400, description="Project required")

    evidence_data = _load_artifact(project, "evidence.json")
    if evidence_data is None:
        abort(404, description="evidence.json not found")

    git_data = evidence_data.get("git", {})
    available = git_data.get("available", False)

    return render_template(
        "git.html",
        project=project,
        git_data=git_data,
        available=available,
    )


# ── AI Context ───────────────────────────────────────────────────────────────


@bp.route("/ai_context")
def ai_context():
    project = request.args.get("project", "")
    if not project or not _project_exists(project):
        abort(404 if project else 400, description="Project required")

    ai_ctx = _load_artifact(project, "evidence-ai-context.json")
    if ai_ctx is None:
        abort(404, description="evidence-ai-context.json not found")

    facts = ai_ctx.get("facts", [])
    metrics = ai_ctx.get("metrics", [])
    unknowns = ai_ctx.get("unknowns", [])
    guidance = ai_ctx.get("guidance_for_llm", "")
    limits = ai_ctx.get("limits", [])

    return render_template(
        "ai_context.html",
        project=project,
        ai_ctx=ai_ctx,
        facts=facts,
        metrics=metrics,
        unknowns=unknowns,
        guidance=guidance,
        limits=limits,
    )


# ── Artifacts ────────────────────────────────────────────────────────────────


@bp.route("/artifacts")
def artifacts():
    project = request.args.get("project", "")
    if not project or not _project_exists(project):
        abort(404 if project else 400, description="Project required")

    paths = _get_artifact_paths(project)
    manifest = _load_artifact(project, "manifest.json")

    items = []
    for label, path in paths.items():
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        content = None
        if exists and path.suffix == ".md":
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                pass

        items.append(
            {
                "label": label,
                "filename": path.name,
                "exists": exists,
                "size": size,
                "content": content,
            }
        )

    return render_template(
        "artifacts.html",
        project=project,
        items=items,
        manifest=manifest,
    )


# ── Error handlers ───────────────────────────────────────────────────────────


@bp.errorhandler(404)
@bp.errorhandler(400)
def handle_error(exc):
    return render_template("error.html", error=exc), exc.code
