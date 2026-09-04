"""
Analyzer #3 — Repository Metrics

Collects quantitative code metrics by reading file contents:
- Total LOC, code lines, comment lines, blank lines
- Per-language LOC breakdown
- Module/package counts
- Test file count
- Migration count
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..constants import EXCLUDED_DIRS, MIGRATION_DIR_NAMES, TEST_FILE_PREFIXES, TEST_FILE_SUFFIXES
from ..evidence import EvidenceBuilder
from ..models import AnalyzerResult, AnalyzerWarning

logger = logging.getLogger(__name__)

# Extensions to count LOC for
LOC_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".html": "html",
    ".htm": "html",
    ".jinja": "html",
    ".jinja2": "html",
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".sql": "sql",
    ".sh": "shell",
}

# Comment markers per language (for comment line detection)
COMMENT_MARKERS: dict[str, list[str]] = {
    "python": ["#"],
    "javascript": ["//", "/*", " *", "*/"],
    "typescript": ["//", "/*", " *", "*/"],
    "html": ["<!--"],
    "css": ["/*", " *", "*/"],
    "sql": ["--", "/*"],
    "shell": ["#"],
}


def run(project_root: Path, evidence: EvidenceBuilder) -> AnalyzerResult:
    result = AnalyzerResult(name="repository")

    try:
        data = _collect_metrics(project_root, evidence)
        result.data = data
    except Exception as exc:
        logger.exception("Repository analyzer failed")
        result.success = False
        result.warnings.append(
            AnalyzerWarning(analyzer="repository", error=str(exc), recoverable=False)
        )

    return result


def _collect_metrics(project_root: Path, evidence: EvidenceBuilder) -> dict:
    """Walk all non-excluded files and collect LOC metrics."""

    total_files = 0
    total_lines = 0
    code_lines = 0
    comment_lines = 0
    blank_lines = 0

    loc_by_lang: dict[str, dict[str, int]] = {}  # lang -> {files, total, code, comment, blank}

    python_packages = 0
    python_modules = 0
    migration_files = 0
    test_files = 0
    largest_files: list[tuple[int, str]] = []  # (lines, rel_path)

    files_read_errors = 0

    for file_path in _iter_files(project_root):
        ext = file_path.suffix.lower()
        lang = LOC_EXTENSIONS.get(ext)
        rel_path = str(file_path.relative_to(project_root)).replace("\\", "/")

        if lang is None:
            continue

        total_files += 1

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"Cannot read {file_path}: {e}")
            files_read_errors += 1
            continue

        lines = content.splitlines()
        n_total = len(lines)
        n_blank = 0
        n_comment = 0
        n_code = 0

        comment_markers = COMMENT_MARKERS.get(lang, [])

        for line in lines:
            stripped = line.strip()
            if not stripped:
                n_blank += 1
            elif comment_markers and any(stripped.startswith(m) for m in comment_markers):
                n_comment += 1
            else:
                n_code += 1

        total_lines += n_total
        code_lines += n_code
        comment_lines += n_comment
        blank_lines += n_blank

        if lang not in loc_by_lang:
            loc_by_lang[lang] = {"files": 0, "total": 0, "code": 0, "comment": 0, "blank": 0}
        loc_by_lang[lang]["files"] += 1
        loc_by_lang[lang]["total"] += n_total
        loc_by_lang[lang]["code"] += n_code
        loc_by_lang[lang]["comment"] += n_comment
        loc_by_lang[lang]["blank"] += n_blank

        # Track largest
        largest_files.append((n_total, rel_path))

        # Python-specific
        if ext == ".py":
            stem_lower = file_path.stem.lower()
            if file_path.name == "__init__.py":
                python_packages += 1

            # Count as module if it has code content
            if n_total > 0:
                python_modules += 1

            # Test file
            if (
                any(stem_lower.startswith(p) for p in TEST_FILE_PREFIXES)
                or any(stem_lower.endswith(s) for s in TEST_FILE_SUFFIXES)
            ):
                test_files += 1

        # Migration file
        if any(part in MIGRATION_DIR_NAMES for part in file_path.parts):
            migration_files += 1

    # Top 10 largest
    largest_files.sort(reverse=True)
    top_largest = [
        {"lines": lines, "file": rel}
        for lines, rel in largest_files[:10]
    ]

    # Emit evidence
    evidence.add_metric("total_loc", total_lines, notes="Total lines including blank/comments")
    evidence.add_metric("code_lines", code_lines)
    evidence.add_metric("comment_lines", comment_lines)
    evidence.add_metric("blank_lines", blank_lines)
    evidence.add_metric("python_packages", python_packages, notes="Count of __init__.py files")
    evidence.add_metric("python_modules", python_modules)
    evidence.add_metric("test_files_loc", test_files)
    evidence.add_metric("migration_files", migration_files)

    for lang, stats in loc_by_lang.items():
        evidence.add_metric(f"loc_{lang}", stats["total"])

    return {
        "total_files_counted": total_files,
        "total_lines": total_lines,
        "code_lines": code_lines,
        "comment_lines": comment_lines,
        "blank_lines": blank_lines,
        "comment_ratio": round(comment_lines / total_lines, 3) if total_lines else 0,
        "loc_by_language": loc_by_lang,
        "python_packages": python_packages,
        "python_modules": python_modules,
        "test_files": test_files,
        "migration_files": migration_files,
        "files_read_errors": files_read_errors,
        "top_10_largest_files": top_largest,
    }


def _iter_files(project_root: Path):
    """Yield all files not under excluded directories."""
    for item in project_root.rglob("*"):
        if item.is_file():
            if not _is_excluded(item, project_root):
                yield item


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return any(part in EXCLUDED_DIRS for part in rel.parts)
