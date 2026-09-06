"""
AIPS Analyzer — CLI entry point (v0.1 productization).

Usage:
    aips-analyze /path/to/project
    python -m aips_analyzer /path/to/project

Produces a complete, portable analysis package under
    output/<project-name>/
containing (where applicable):
    - evidence.json             (raw)
    - evidence-aggregated.json   (Aggregator v2)
    - evidence-ai-context.json   (LLM-ready projection)
    - evidence-audit.md          (human-readable v1 audit)
    - manifest.json              (deterministic, portable)

The package is deterministic for the same analyzer version and
project state. Manifest is portable (no absolute paths).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .. import __name_display__, __version__
from ..analyzer import analyze_project
from ..manifest import MANIFEST_SCHEMA, MANIFEST_VERSION


def _configure_utf8_io() -> None:
    """
    Make stdout/stderr safe for non-ASCII characters on Windows consoles
    (cp1251 by default). POSIX is usually a no-op because UTF-8 is
    already the default.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def setup_logging(verbose: bool, log_file: Path | None = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    logging.getLogger("aips_analyzer.analyzers").setLevel(
        logging.DEBUG if verbose else logging.WARNING
    )


def _resolve_package_dir(output_dir: Path, project_name: str) -> Path:
    """Resolve package dir from output_dir, ensuring portability."""
    return output_dir / project_name


def _validate_target(project_path: Path) -> None:
    """Pre-flight validation. Raise appropriate errors per AA-019 §6."""
    if not project_path.exists():
        raise FileNotFoundError(f"Project path does not exist: {project_path}")
    if not project_path.is_dir():
        raise NotADirectoryError(f"Project path is not a directory: {project_path}")


def print_summary(
    report,
    package_dir: Path,
) -> None:
    """Print a human-readable summary to stdout.

    AA-019 §8 target UX. Lists the 5 canonical artifacts in the
    output package, plus a small analytic summary.
    """
    proj = report.project
    disc = report.discovery
    repo = report.repository
    git_data = report.git
    arch = report.architecture
    warnings = report.warnings

    print()
    print("=" * 64)
    print(f"  AIPS Analyzer  v{__version__}")
    print("=" * 64)
    print()
    print(f"  Project  : {proj.get('name', '?')}")
    print(f"  Analyzed : {proj.get('analyzed_at', '?')}")
    print(f"  Duration : {proj.get('analysis_duration_seconds', '?')}s")
    print()
    print("  ── Summary ──────────────────────────────────────")
    print(f"  Total files       : {disc.get('total_files', '?')}")
    print(f"  Python files      : {disc.get('python_files_count', '?')}")
    print(f"  Test files        : {disc.get('test_files_count', '?')}")
    print(f"  Total LOC         : {repo.get('total_lines', '?')}")
    print(f"  Python modules    : {repo.get('python_modules', '?')}")
    print(f"  Git available     : {git_data.get('available', False)}")
    if git_data.get("available"):
        print(f"  Git branch        : {git_data.get('current_branch', '?')}")
    print(f"  Architecture mods : {arch.get('total_modules', '?')}")
    print(
        f"  Cyclic deps       : {arch.get('cyclic_dependencies', {}).get('count', 0)}"
    )
    print(f"  Evidence items    : {len(report.evidence)}")
    print(f"  Warnings          : {len(warnings)}")
    print()
    print("  ── Output package ──────────────────────────────")
    for fname in (
        "evidence.json",
        "evidence-aggregated.json",
        "evidence-ai-context.json",
        "evidence-audit.md",
        "manifest.json",
    ):
        path = package_dir / fname
        if path.exists():
            print(f"  {fname:<28}  {path}")
    print()
    print(f"  Manifest schema: {MANIFEST_SCHEMA} v{MANIFEST_VERSION}")
    print()
    print("  Analysis completed successfully.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="aips-analyze",
        description=(
            "AIPS Analyzer — Deterministic static analysis of software projects (v0.1)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  aips-analyze /path/to/project
  aips-analyze /path/to/project --output ./my_results
  aips-analyze /path/to/project --verbose
  aips-analyze /path/to/project --no-output
        """,
    )
    parser.add_argument(
        "project",
        metavar="PROJECT_PATH",
        help="Path to the project directory to analyze",
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="OUTPUT_DIR",
        default="output",
        help="Directory to save the analysis package (default: ./output)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    parser.add_argument(
        "--no-output",
        action="store_true",
        help="Do not save any artifacts (print only)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__name_display__} {__version__}",
    )

    args = parser.parse_args()
    _configure_utf8_io()
    project_path = Path(args.project).resolve()

    # Pre-flight validation (AA-019 §6: error handling per failure mode).
    try:
        _validate_target(project_path)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)

    output_dir = None if args.no_output else Path(args.output).resolve()
    log_file = (
        None if output_dir is None else output_dir / project_path.name / "run.log"
    )
    setup_logging(args.verbose, log_file)

    print(f"\nAnalyzing project: {project_path}")
    print(f"Output directory : {output_dir or '(none — use --output to save)'}\n")

    # Run analysis. Per AA-019 §6, partial analyzer failure does not
    # necessarily destroy the whole report — analyze_project already
    # isolates per-analyzer failures into AnalyzerWarning entries.
    try:
        report = analyze_project(
            project_path=project_path,
            output_dir=output_dir,
        )
    except Exception as exc:
        print(f"\nUnexpected error: {exc}", file=sys.stderr)
        logging.getLogger(__name__).exception("Fatal error during analysis")
        sys.exit(2)

    if output_dir is not None:
        package_dir = _resolve_package_dir(output_dir, report.project["name"])
        print_summary(report, package_dir)
    else:
        # No artifacts: minimal summary.
        print(f"Project: {report.project.get('name', '?')}")
        print(f"Evidence items: {len(report.evidence)}")
        print("Run with --output DIR to save the analysis package.")

    sys.exit(0)


if __name__ == "__main__":
    main()
