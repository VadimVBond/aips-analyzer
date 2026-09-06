"""
AIPS Analyzer — Main Orchestrator

Entry point for the analysis engine.
Each analyzer is run independently — failures are isolated.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .analyzers import (
    architecture,
    dependencies,
    discovery,
    git,
    repository,
    technology,
)
from .evidence import EvidenceBuilder, serialize_report
from .models import AnalyzerWarning, EvidenceReport

logger = logging.getLogger(__name__)


def analyze_project(
    project_path: str | Path,
    output_dir: str | Path | None = None,
) -> EvidenceReport:
    """
    Analyze a software project and return a structured EvidenceReport.

    This is the main engine entry point. It can be called from:
    - CLI
    - Flask (future)
    - Celery (future)
    - API (future)

    Args:
        project_path: Absolute or relative path to the project to analyze.
        output_dir:   Where to save evidence.json. If None, doesn't save.

    Returns:
        EvidenceReport with all collected data.
    """
    project_root = Path(project_path).resolve()

    if not project_root.exists():
        raise FileNotFoundError(f"Project path does not exist: {project_root}")
    if not project_root.is_dir():
        raise NotADirectoryError(f"Project path is not a directory: {project_root}")

    logger.info(f"Starting analysis of: {project_root}")
    start_time = time.monotonic()

    # Initialize evidence builder (shared across all analyzers)
    evidence = EvidenceBuilder()

    # Initialize report
    report = EvidenceReport(
        project={
            "name": project_root.name,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    all_warnings: list[AnalyzerWarning] = []

    # ── Run analyzers ──────────────────────────────────────────────────────
    # Order matters: discovery first (provides context), architecture last (needs full scan)

    analyzers = [
        ("discovery", discovery.run),
        ("technology", technology.run),
        ("dependencies", dependencies.run),
        ("repository", repository.run),
        ("git", git.run),
        ("architecture", architecture.run),
    ]

    for name, run_fn in analyzers:
        logger.info(f"  Running analyzer: {name}")
        t0 = time.monotonic()
        try:
            result = run_fn(project_root, evidence)
            elapsed = time.monotonic() - t0

            # Store result data in report
            setattr(report, name, result.data)

            # Collect warnings
            all_warnings.extend(result.warnings)

            if result.success:
                logger.info(f"  ✓ {name} ({elapsed:.1f}s)")
            else:
                logger.warning(f"  ✗ {name} FAILED ({elapsed:.1f}s)")

        except Exception as exc:
            elapsed = time.monotonic() - t0
            logger.error(f"  ✗ {name} CRASHED ({elapsed:.1f}s): {exc}", exc_info=True)
            all_warnings.append(
                AnalyzerWarning(
                    analyzer=name,
                    error=f"Unexpected crash: {exc}",
                    recoverable=True,
                    details="See run.log for stack trace",
                )
            )
            # Set empty data so report remains valid
            setattr(report, name, {"available": False, "error": str(exc)})

    # ── Finalize report ────────────────────────────────────────────────────

    # Attach all evidence items from the shared builder
    report.evidence = evidence.items

    # Attach warnings
    report.warnings = all_warnings

    # Build metrics list (flat)
    from .evidence import build_metrics_list

    report.metrics = build_metrics_list(
        {
            "discovery": report.discovery,
            "repository": report.repository,
        }
    )

    # Total elapsed
    total_elapsed = time.monotonic() - start_time
    report.project["analysis_duration_seconds"] = round(total_elapsed, 2)
    report.project["evidence_items_count"] = len(report.evidence)
    report.project["warnings_count"] = len(all_warnings)

    logger.info(
        f"Analysis complete in {total_elapsed:.1f}s. "
        f"Evidence items: {len(report.evidence)}. "
        f"Warnings: {len(all_warnings)}."
    )

    # ── Save output package ─────────────────────────────────────────────
    # Canonical v0.1 pipeline (AA-019 §2):
    #   raw evidence → aggregated (v2) → AI context → manifest
    # All artifacts share the same package_dir. Aggregator and AI
    # Context reuse the existing scripts/audit_evidence.py
    # implementations to keep a single canonical transformation.
    if output_dir is not None:
        package_dir = Path(output_dir) / report.project["name"]
        package_dir.mkdir(parents=True, exist_ok=True)
        output_path = package_dir / "evidence.json"
        # Use a relative, portable path in the artifact itself,
        # so the serialized evidence does not leak the absolute
        # filesystem path of the machine that produced it.
        try:
            relative_output = output_path.relative_to(Path.cwd())
            report.project["output_file"] = str(relative_output).replace("\\", "/")
        except ValueError:
            report.project["output_file"] = f"{report.project['name']}/evidence.json"
        serialize_report(report, output_path)
        logger.info(f"Saved to: {output_path}")

        # Aggregated v2 + AI Context + Audit markdown (canonical layer)
        try:
            _emit_aggregated_package(report, output_path, package_dir)
        except Exception as exc:
            # Aggregator failure must not lose the raw evidence.
            # Per AA-019 §6: "partial failure does not unnecessarily
            # destroy unrelated analysis."
            logger.warning(
                f"Failed to emit aggregated package ({exc}); "
                f"raw evidence is still available at {output_path}"
            )

    return report


def _emit_aggregated_package(report, evidence_path: Path, package_dir: Path) -> None:
    """Emit aggregated v2 + AI context + audit + manifest.

    Wraps scripts/audit_evidence.py functions. Kept as a private
    helper here so the canonical pipeline lives in a single place
    (aips_analyzer.analyzer.analyze_project) and does not depend on
    a user invoking scripts/audit_evidence.py manually.
    """
    import importlib.util
    import sys as _sys

    # Load scripts/audit_evidence.py without making scripts/ a package.
    audit_script = (
        Path(__file__).resolve().parent.parent / "scripts" / "audit_evidence.py"
    )
    spec = importlib.util.spec_from_file_location("aips_audit_evidence", audit_script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load audit_evidence module from {audit_script}")
    audit_mod = importlib.util.module_from_spec(spec)
    _sys.modules.setdefault("aips_audit_evidence", audit_mod)
    spec.loader.exec_module(audit_mod)

    # Reload the just-written evidence.json so that aggregate_v2 sees
    # the same content the CLI serialised (deterministic contract).
    evidence_dict = json.loads(evidence_path.read_text(encoding="utf-8"))

    # Reuse aggregate_v2 + render_ai_context functions (canonical).
    aggregated = audit_mod.aggregate_v2_with_aa011(evidence_dict)
    aggregated_path = package_dir / "evidence-aggregated.json"
    # sort_keys=True for byte-identical output across runs.
    aggregated_path.write_text(
        __import__("json").dumps(
            aggregated, indent=2, ensure_ascii=False, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )

    # v1 evidence-audit.md summary (human-readable, deterministic given
    # the same input).
    audit_v1 = audit_mod.audit_evidence(evidence_dict, generated_at=None)
    audit_md_path = package_dir / "evidence-audit.md"
    audit_mod._emit_markdown(audit_v1, audit_md_path)

    # AI Context (uses aggregate_v2 output; deterministic projection).
    ai_ctx = audit_mod.render_ai_context(aggregated)
    ai_ctx_path = package_dir / "evidence-ai-context.json"
    # sort_keys=True for byte-identical output across runs.
    ai_ctx_path.write_text(
        __import__("json").dumps(ai_ctx, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    # manifest.json: deterministic, portable, summarizes the package.
    from .manifest import write_manifest

    write_manifest(
        package_dir=package_dir,
        project_name=report.project["name"],
        analyzer_version=__version__,
        analyzed_at=report.project.get("analyzed_at"),
    )
