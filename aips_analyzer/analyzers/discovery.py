"""
Analyzer #1 — Discovery

Traverses the project filesystem and collects structural information:
- File counts by type
- Directory counts
- Configuration files presence
- Test/migration directories
- Django apps heuristic detection
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..constants import (
    DJANGO_APP_INDICATORS,
    DJANGO_PROJECT_INDICATORS,
    EXCLUDED_DIRS,
    EXTENSION_MAP,
    FILENAME_MAP,
    MIGRATION_DIR_NAMES,
    TEST_DIR_NAMES,
    TEST_FILE_PREFIXES,
    TEST_FILE_SUFFIXES,
)
from ..evidence import EvidenceBuilder
from ..models import AnalyzerResult, AnalyzerWarning, EvidenceSource

logger = logging.getLogger(__name__)


def run(project_root: Path, evidence: EvidenceBuilder) -> AnalyzerResult:
    """
    Run the Discovery Analyzer on project_root.

    Returns AnalyzerResult with:
    - data: structured discovery summary
    - evidence: EvidenceItems generated
    - warnings: any non-fatal issues
    """
    result = AnalyzerResult(name="discovery")

    try:
        data = _discover(project_root, evidence)
        result.data = data
        result.evidence = evidence.items
    except Exception as exc:
        logger.exception("Discovery analyzer failed")
        result.success = False
        result.warnings.append(
            AnalyzerWarning(
                analyzer="discovery",
                error=str(exc),
                recoverable=False,
            )
        )

    return result


def _is_excluded(path: Path) -> bool:
    """Return True if this path (or any ancestor) is in EXCLUDED_DIRS."""
    for part in path.parts:
        if part in EXCLUDED_DIRS:
            return True
        # Handle glob patterns like *.egg-info
        for pattern in EXCLUDED_DIRS:
            if "*" in pattern and Path(part).match(pattern):
                return True
    return False


def _classify_file(path: Path) -> str:
    """Return a category string for a file path."""
    name_lower = path.name.lower()
    if name_lower in FILENAME_MAP:
        return FILENAME_MAP[name_lower]
    suffix = path.suffix.lower()
    return EXTENSION_MAP.get(suffix, "other")


def _discover(project_root: Path, evidence: EvidenceBuilder) -> dict:
    """Walk the project tree and collect discovery data."""

    # Counters
    total_files = 0
    total_dirs = 0
    files_by_type: dict[str, int] = {}
    config_files_found: list[str] = []
    test_files: list[str] = []
    migration_dirs: list[str] = []
    django_apps: list[str] = []
    python_files: list[str] = []
    html_files: list[str] = []
    css_files: list[str] = []
    js_files: list[str] = []
    json_files: list[str] = []
    yaml_files: list[str] = []
    sql_files: list[str] = []
    markdown_files: list[str] = []
    template_files: list[str] = []

    # Special file presence flags
    has_manage_py = False
    has_pyproject_toml = False
    has_requirements_txt = False
    has_package_json = False
    has_dockerfile = False
    has_docker_compose = False
    has_gitignore = False
    has_pytest_ini = False
    has_conftest = False

    for path in _walk(project_root):
        if path.is_dir():
            total_dirs += 1
            rel_dir = path.relative_to(project_root)

            # Check for migration directories
            if path.name.lower() in MIGRATION_DIR_NAMES:
                migration_dirs.append(str(rel_dir))

            # Check for test directories
            if path.name.lower() in TEST_DIR_NAMES:
                pass  # counted via test files

            # Check for Django app heuristic
            _check_django_app(path, project_root, django_apps)

        else:
            total_files += 1
            rel = path.relative_to(project_root)
            rel_str = str(rel).replace("\\", "/")
            category = _classify_file(path)
            files_by_type[category] = files_by_type.get(category, 0) + 1

            # Accumulate by language
            if category in ("python", "python_stub"):
                python_files.append(rel_str)
            elif category == "html":
                html_files.append(rel_str)
            elif category == "html_template":
                template_files.append(rel_str)
            elif category == "css":
                css_files.append(rel_str)
            elif category in ("javascript", "typescript"):
                js_files.append(rel_str)
            elif category == "json":
                json_files.append(rel_str)
            elif category == "yaml":
                yaml_files.append(rel_str)
            elif category == "sql":
                sql_files.append(rel_str)
            elif category == "markdown":
                markdown_files.append(rel_str)

            # Test file detection
            stem_lower = path.stem.lower()
            if (
                any(stem_lower.startswith(p) for p in TEST_FILE_PREFIXES)
                or any(stem_lower.endswith(s) for s in TEST_FILE_SUFFIXES)
            ) and category == "python":
                test_files.append(rel_str)

            # Special file flags
            name_lower = path.name.lower()
            if name_lower == "manage.py":
                has_manage_py = True
            elif name_lower == "pyproject.toml":
                has_pyproject_toml = True
            elif name_lower == "requirements.txt":
                has_requirements_txt = True
            elif name_lower == "package.json" and "node_modules" not in rel_str:
                has_package_json = True
            elif name_lower in ("dockerfile", ".dockerfile"):
                has_dockerfile = True
            elif name_lower in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml"):
                has_docker_compose = True
            elif name_lower == ".gitignore":
                has_gitignore = True
            elif name_lower in ("pytest.ini", "setup.cfg") and category in ("ini", "cfg"):
                has_pytest_ini = True
            elif name_lower == "conftest.py":
                has_conftest = True

    # Config files summary
    config_checks = {
        "pyproject.toml": has_pyproject_toml,
        "requirements.txt": has_requirements_txt,
        "package.json": has_package_json,
        "Dockerfile": has_dockerfile,
        "docker-compose": has_docker_compose,
        ".gitignore": has_gitignore,
        "pytest.ini/setup.cfg": has_pytest_ini,
        "conftest.py": has_conftest,
        "manage.py": has_manage_py,
    }
    config_files_found = [name for name, present in config_checks.items() if present]

    # Emit evidence items
    evidence.add_metric(
        "total_files", total_files,
        notes=f"Excluding: {', '.join(sorted(EXCLUDED_DIRS)[:8])}..."
    )
    evidence.add_metric("total_directories", total_dirs)
    evidence.add_metric("python_files", len(python_files))
    evidence.add_metric("html_files", len(html_files))
    evidence.add_metric("html_template_files", len(template_files))
    evidence.add_metric("css_files", len(css_files))
    evidence.add_metric("js_files", len(js_files))
    evidence.add_metric("json_files", len(json_files))
    evidence.add_metric("yaml_files", len(yaml_files))
    evidence.add_metric("sql_files", len(sql_files))
    evidence.add_metric("markdown_files", len(markdown_files))
    evidence.add_metric("test_files", len(test_files))
    evidence.add_metric("migration_directories", len(migration_dirs))
    evidence.add_metric("django_apps_heuristic", len(django_apps))

    if has_manage_py:
        evidence.add_technology(
            "Django",
            "manage.py present",
            source_file="manage.py",
            source_method="file_presence",
            notes="manage.py is a strong indicator of a Django project",
        )

    return {
        "project_root": str(project_root),
        "total_files": total_files,
        "total_directories": total_dirs,
        "files_by_type": dict(sorted(files_by_type.items(), key=lambda x: -x[1])),
        "python_files_count": len(python_files),
        "html_files_count": len(html_files),
        "template_files_count": len(template_files),
        "css_files_count": len(css_files),
        "js_files_count": len(js_files),
        "json_files_count": len(json_files),
        "yaml_files_count": len(yaml_files),
        "sql_files_count": len(sql_files),
        "markdown_files_count": len(markdown_files),
        "test_files_count": len(test_files),
        "test_files": test_files,
        "migration_dirs": migration_dirs,
        "django_apps_heuristic": django_apps,
        "config_files_present": config_files_found,
        "config_flags": config_checks,
    }


def _walk(root: Path):
    """
    Yield all paths (files and dirs) under root, skipping EXCLUDED_DIRS.
    """
    try:
        entries = list(root.iterdir())
    except PermissionError as e:
        logger.warning(f"Cannot access {root}: {e}")
        return

    for entry in entries:
        # Skip excluded directories
        if entry.is_dir():
            if entry.name in EXCLUDED_DIRS or any(
                entry.match(p) for p in EXCLUDED_DIRS if "*" in p
            ):
                continue
            yield entry
            yield from _walk(entry)
        else:
            yield entry


def _check_django_app(
    directory: Path, project_root: Path, django_apps: list[str]
) -> None:
    """
    Heuristic: a directory is likely a Django app if it contains
    at least 2 of the Django app indicator files.
    """
    indicators_found = sum(
        1
        for indicator in DJANGO_APP_INDICATORS
        if (directory / indicator).exists()
    )
    if indicators_found >= 2:
        rel = str(directory.relative_to(project_root)).replace("\\", "/")
        if rel not in django_apps:
            django_apps.append(rel)
