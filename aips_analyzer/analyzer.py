"""
AIPS Analyzer — Main Orchestrator

Entry point for the analysis engine.
Each analyzer is run independently — failures are isolated.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .analyzers import architecture, dependencies, discovery, git, repository, technology
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
            "root": str(project_root),
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

    # ── Save output ────────────────────────────────────────────────────────
    if output_dir is not None:
        output_path = Path(output_dir) / report.project["name"] / "evidence.json"
        serialize_report(report, output_path)
        report.project["output_file"] = str(output_path)
        logger.info(f"Saved to: {output_path}")

    return report
