"""
AIPS Analyzer — CLI entry point.

Usage:
    python -m aips_analyzer /path/to/project
    aips-analyze /path/to/project [--output ./output] [--verbose]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .. import __version__, __name_display__
from ..analyzer import analyze_project


def _configure_utf8_io() -> None:
    """
    Make stdout/stderr safe for non-ASCII characters on Windows consoles
    (cp1251 by default) and other locales that would otherwise raise
    UnicodeEncodeError. On POSIX this is usually a no-op because UTF-8
    is already the default.
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
            # Some environments (pytest capture, IDE consoles) don't allow
            # reconfigure. Failing silently is the right thing to do here.
            pass

BANNER = f"""
╔══════════════════════════════════════════╗
║        AIPS Analyzer  v{__version__}           ║
║  Deterministic Project Analysis Engine  ║
║  No AI · No Code Execution · Read-only  ║
╚══════════════════════════════════════════╝
"""


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
    # Quiet noisy loggers
    logging.getLogger("aips_analyzer.analyzers").setLevel(
        logging.DEBUG if verbose else logging.WARNING
    )


def print_summary(report, output_path: Path | None) -> None:
    """Print a human-readable summary to stdout."""
    proj = report.project
    disc = report.discovery
    repo = report.repository
    dep = report.dependencies
    git_data = report.git
    arch = report.architecture

    print(BANNER)
    print(f"  Project  : {proj.get('name', '?')}")
    print(f"  Analyzed : {proj.get('analyzed_at', '?')}")
    print(f"  Duration : {proj.get('analysis_duration_seconds', '?')}s")
    print()
    print("  ─── Discovery ──────────────────────────────────")
    print(f"  Total files          : {disc.get('total_files', '?')}")
    print(f"  Total directories    : {disc.get('total_directories', '?')}")
    print(f"  Python files         : {disc.get('python_files_count', '?')}")
    print(f"  HTML/template files  : {(disc.get('html_files_count', 0) or 0) + (disc.get('template_files_count', 0) or 0)}")
    print(f"  CSS files            : {disc.get('css_files_count', '?')}")
    print(f"  JS files             : {disc.get('js_files_count', '?')}")
    print(f"  Test files           : {disc.get('test_files_count', '?')}")
    print(f"  Migration dirs       : {disc.get('migration_dirs', [])}")
    print(f"  Django apps (heur.)  : {disc.get('django_apps_heuristic', [])}")
    print()
    print("  ─── Repository Metrics ─────────────────────────")
    print(f"  Total LOC            : {repo.get('total_lines', '?')}")
    print(f"  Code lines           : {repo.get('code_lines', '?')}")
    print(f"  Comment lines        : {repo.get('comment_lines', '?')}")
    print(f"  Python LOC           : {(repo.get('loc_by_language') or {}).get('python', {}).get('total', '?')}")
    print(f"  Python modules       : {repo.get('python_modules', '?')}")
    print(f"  Python packages      : {repo.get('python_packages', '?')}")
    print()
    print("  ─── Dependencies ───────────────────────────────")
    py_dep = dep.get("python", {})
    nd_dep = dep.get("node", {})
    print(f"  Python PM            : {py_dep.get('package_manager', '?')}")
    print(f"  Python prod deps     : {py_dep.get('production_count', '?')}")
    print(f"  Python dev deps      : {py_dep.get('dev_count', '?')}")
    print(f"  Lockfile             : {py_dep.get('lockfile_file', 'none')}")
    if nd_dep.get("production_count", 0) or nd_dep.get("dev_count", 0):
        print(f"  Node PM              : {nd_dep.get('package_manager', '?')}")
        print(f"  Node prod deps       : {nd_dep.get('production_count', '?')}")
        print(f"  Node dev deps        : {nd_dep.get('dev_count', '?')}")
    print()
    print("  ─── Git ─────────────────────────────────────────")
    if git_data.get("available"):
        print(f"  Branch               : {git_data.get('current_branch', '?')}")
        print(f"  Commits              : {git_data.get('total_commits', '?')}")
        print(f"  Contributors         : {git_data.get('contributors_count', '?')}")
        print(f"  Branches             : {git_data.get('branches_count', '?')}")
        print(f"  First commit         : {git_data.get('first_commit_date', '?')}")
        print(f"  Latest commit        : {git_data.get('latest_commit_date', '?')}")
    else:
        print(f"  Git not available    : {git_data.get('reason', git_data.get('error', '?'))}")
    print()
    print("  ─── Architecture (AST) ─────────────────────────")
    print(f"  Python modules       : {arch.get('total_modules', '?')}")
    print(f"  Django apps (AST)    : {len(arch.get('django_apps', []))}")
    print(f"  Model modules        : {len(arch.get('model_modules', []))}")
    print(f"  View modules         : {len(arch.get('view_modules', []))}")
    print(f"  URL modules          : {len(arch.get('url_modules', []))}")
    print(f"  Celery task modules  : {len(arch.get('celery_task_modules', []))}")
    print(f"  Cyclic deps          : {arch.get('cyclic_dependencies', {}).get('count', 0)}")
    print(f"  Parse errors         : {len(arch.get('parse_errors', []))}")
    print()
    print("  ─── Technology Signals ──────────────────────────")
    tech_signals = report.technology.get("technology_signals", {})
    if tech_signals:
        for tech, signals in sorted(tech_signals.items()):
            signal_types = set(s["signal_type"] for s in signals)
            print(f"  {tech:<24} : {len(signals)} signal(s) [{', '.join(sorted(signal_types))}]")
    else:
        print("  (no technology signals)")
    print()
    print("  ─── Evidence Summary ────────────────────────────")
    print(f"  Total evidence items : {len(report.evidence)}")
    print(f"  Warnings             : {len(report.warnings)}")
    if report.warnings:
        print()
        print("  ─── Warnings ────────────────────────────────────")
        for w in report.warnings:
            mark = "⚠" if w.recoverable else "✗"
            print(f"  {mark} [{w.analyzer}] {w.error}")

    print()
    if output_path:
        print(f"  Evidence saved to: {output_path}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="aips-analyze",
        description="AIPS Analyzer — Deterministic static analysis of software projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m aips_analyzer /path/to/my_project
  python -m aips_analyzer /path/to/my_project --output ./output --verbose
  aips-analyze /path/to/my_project
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
        help="Directory to save evidence.json (default: ./output)",
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
        help="Do not save evidence.json (print only)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__name_display__} {__version__}",
    )

    args = parser.parse_args()
    _configure_utf8_io()
    project_path = Path(args.project).resolve()

    # Determine output dir and log file
    output_dir = None if args.no_output else Path(args.output).resolve()
    log_file = (
        output_dir / project_path.name / "run.log"
        if output_dir
        else None
    )

    setup_logging(args.verbose, log_file)

    print(f"\nAnalyzing project: {project_path}")
    print(f"Output directory : {output_dir or '(none — use --output to save)'}\n")

    try:
        report = analyze_project(
            project_path=project_path,
            output_dir=output_dir,
        )
    except FileNotFoundError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except NotADirectoryError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        logging.getLogger(__name__).exception("Fatal error during analysis")
        sys.exit(2)

    # Determine output path for summary
    output_path = (
        output_dir / project_path.name / "evidence.json"
        if output_dir
        else None
    )

    print_summary(report, output_path)
    sys.exit(0)


if __name__ == "__main__":
    main()
