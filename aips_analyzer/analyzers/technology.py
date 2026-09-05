"""
Analyzer #2 — Technology Detection

Records OBSERVATIONS about technologies found in the project.
Does NOT make final conclusions like "framework = Django".
Instead records evidence signals with provenance.

Each signal has:
- technology name
- signal_type: how it was detected
- source: where exactly (file, section, line, pattern)
- detail: what was observed (version, import string, etc.)
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

from ..evidence import EvidenceBuilder
from ..models import AnalyzerResult, AnalyzerWarning, EvidenceSource, TechnologyObservation

logger = logging.getLogger(__name__)

# ─── Technology signal definitions ────────────────────────────────────────

# Python import patterns: technology → list of import prefixes to look for
IMPORT_PATTERNS: dict[str, list[str]] = {
    "Django": ["django"],
    "Celery": ["celery"],
    "Django REST Framework": ["rest_framework"],
    "HTMX": [],  # not a Python import — detected via HTML patterns
    "PostgreSQL/psycopg": ["psycopg", "psycopg2", "psycopg3"],
    "Redis": ["redis"],
    "Pytest": ["pytest"],
    "Factory Boy": ["factory"],
    "Faker": ["faker"],
    "Pydantic": ["pydantic"],
    "SQLAlchemy": ["sqlalchemy"],
    "FastAPI": ["fastapi"],
    "Flask": ["flask"],
    "Pillow": ["PIL"],
    "Boto3/AWS": ["boto3", "botocore"],
    "Stripe": ["stripe"],
    "Sentry": ["sentry_sdk"],
    "WhiteNoise": ["whitenoise"],
    "Channels/Django": ["channels"],
    "Huey": ["huey"],
    "RQ": ["rq"],
}

# Dependency file package name → technology
PACKAGE_NAME_PATTERNS: dict[str, str] = {
    "django": "Django",
    "djangorestframework": "Django REST Framework",
    "celery": "Celery",
    "redis": "Redis",
    "psycopg": "PostgreSQL/psycopg",
    "psycopg2": "PostgreSQL/psycopg",
    "psycopg2-binary": "PostgreSQL/psycopg",
    "psycopg3": "PostgreSQL/psycopg",
    "pytest": "Pytest",
    "pytest-django": "Pytest + Django",
    "factory-boy": "Factory Boy",
    "faker": "Faker",
    "pydantic": "Pydantic",
    "sqlalchemy": "SQLAlchemy",
    "fastapi": "FastAPI",
    "flask": "Flask",
    "pillow": "Pillow",
    "boto3": "Boto3/AWS",
    "stripe": "Stripe",
    "sentry-sdk": "Sentry",
    "whitenoise": "WhiteNoise",
    "channels": "Channels/Django",
    "huey": "Huey",
    "rq": "RQ",
    "uvicorn": "Uvicorn",
    "gunicorn": "Gunicorn",
    "dj-database-url": "Django DB URL config",
    "django-cors-headers": "Django CORS headers",
    "django-environ": "django-environ",
    "python-decouple": "python-decouple",
    "coverage": "Coverage.py",
    "black": "Black (formatter)",
    "ruff": "Ruff (linter)",
    "mypy": "MyPy",
    "flake8": "Flake8",
    "pre-commit": "pre-commit",
}

# HTML/template content patterns for frontend tech
HTML_CONTENT_PATTERNS: dict[str, str] = {
    "HTMX": r'hx-[a-z]+',
    "Alpine.js": r'x-[a-z]+\s*=|Alpine\.js',
    "Bootstrap": r'class="[^"]*\b(container|row|col-|btn|navbar|modal)\b',
    "Tailwind CSS": r'class="[^"]*\b(flex|grid|text-\w+|bg-\w+|p-\d+|m-\d+)\b',
    "Chart.js": r'Chart\.js|new Chart\(',
    "jQuery": r'\$\(|jQuery\(',
}


def run(project_root: Path, evidence: EvidenceBuilder) -> AnalyzerResult:
    """
    Run Technology Detection Analyzer.

    Scans:
    1. pyproject.toml [dependencies] / [dev-dependencies]
    2. requirements*.txt files
    3. package.json
    4. Python source files for import statements (sample)
    5. HTML/template files for frontend patterns
    6. Presence of characteristic project files
    """
    result = AnalyzerResult(name="technology")

    try:
        observations, signals_data = _detect_technologies(project_root, evidence)
        result.data = {
            "observations": [o.to_dict() for o in observations],
            "technology_signals": signals_data,
            "note": (
                "These are raw observations/signals, not final verdicts. "
                "Each signal has provenance (source file, section, method)."
            ),
        }
    except Exception as exc:
        logger.exception("Technology analyzer failed")
        result.success = False
        result.warnings.append(
            AnalyzerWarning(analyzer="technology", error=str(exc), recoverable=False)
        )

    return result


def _detect_technologies(
    project_root: Path, evidence: EvidenceBuilder
) -> tuple[list[TechnologyObservation], dict]:
    """Collect all technology observations."""
    observations: list[TechnologyObservation] = []

    # Group by technology for the summary
    tech_signals: dict[str, list[dict]] = {}

    # Deduplicate identical observations:
    # identical = same (technology, signal_type, source.file, source.pattern)
    # Provenance information (section/line) is preserved on first occurrence.
    seen: set[tuple[str, str, str | None, str | None]] = set()

    def record(obs: TechnologyObservation) -> None:
        key = (obs.technology, obs.signal_type, obs.source.file, obs.source.pattern)
        if key in seen:
            return
        seen.add(key)
        observations.append(obs)
        t = obs.technology
        if t not in tech_signals:
            tech_signals[t] = []
        tech_signals[t].append({
            "signal_type": obs.signal_type,
            "source": obs.source.to_dict(),
            "detail": obs.detail,
            "confidence": obs.confidence,
        })
        # Also emit as evidence
        evidence.add_technology(
            technology=t,
            value=obs.detail or obs.signal_type,
            source_file=obs.source.file,
            source_section=obs.source.section,
            source_method=obs.signal_type,
            source_pattern=obs.source.pattern,
        )

    # 1. pyproject.toml
    _scan_pyproject_toml(project_root, record)

    # 2. requirements*.txt files
    _scan_requirements_files(project_root, record)

    # 3. package.json
    _scan_package_json(project_root, record)

    # 4. Python imports (sample — don't read ALL files, just scan imports)
    _scan_python_imports(project_root, record)

    # 5. HTML/template patterns
    _scan_html_patterns(project_root, record)

    # 6. Characteristic file presence
    _scan_file_presence(project_root, record)

    # 7. Django settings patterns
    _scan_django_settings(project_root, record)

    return observations, tech_signals


def _scan_pyproject_toml(project_root: Path, record) -> None:
    """Parse pyproject.toml for dependency declarations."""
    toml_path = project_root / "pyproject.toml"
    if not toml_path.exists():
        return

    try:
        if sys.version_info >= (3, 11):
            import tomllib
            content = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        else:
            try:
                import tomllib
                content = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            except ImportError:
                try:
                    import tomli as tomllib  # type: ignore
                    content = tomllib.loads(toml_path.read_text(encoding="utf-8"))
                except ImportError:
                    _scan_toml_as_text(toml_path, record)
                    return
    except Exception as e:
        logger.warning(f"Failed to parse pyproject.toml: {e}")
        return

    rel_path = "pyproject.toml"

    # PEP 621 [project.dependencies]
    project_deps = content.get("project", {}).get("dependencies", [])
    _process_dep_list(project_deps, rel_path, "project.dependencies", record)

    # PEP 621 [project.optional-dependencies]
    optional_deps = content.get("project", {}).get("optional-dependencies", {})
    for group, deps in optional_deps.items():
        _process_dep_list(deps, rel_path, f"project.optional-dependencies.{group}", record)

    # Poetry [tool.poetry.dependencies]
    poetry_deps = content.get("tool", {}).get("poetry", {}).get("dependencies", {})
    _process_dep_dict(poetry_deps, rel_path, "tool.poetry.dependencies", record)

    poetry_dev = content.get("tool", {}).get("poetry", {}).get("dev-dependencies", {})
    _process_dep_dict(poetry_dev, rel_path, "tool.poetry.dev-dependencies", record)

    # uv [tool.uv.dev-dependencies]
    uv_dev = content.get("tool", {}).get("uv", {}).get("dev-dependencies", [])
    _process_dep_list(uv_dev, rel_path, "tool.uv.dev-dependencies", record)


def _scan_toml_as_text(toml_path: Path, record) -> None:
    """Fallback: scan pyproject.toml as plain text for known package names."""
    try:
        text = toml_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip().strip('"').strip("'").lower()
            for pkg_name, tech in PACKAGE_NAME_PATTERNS.items():
                if stripped.startswith(pkg_name):
                    record(TechnologyObservation(
                        technology=tech,
                        signal_type="dependency_declaration",
                        source=EvidenceSource(
                            file="pyproject.toml",
                            section="unknown (text fallback)",
                            method="text_scan",
                            pattern=pkg_name,
                        ),
                        detail=f"package: {pkg_name}",
                        confidence=0.8,
                    ))
    except Exception as e:
        logger.warning(f"Text fallback scan of pyproject.toml failed: {e}")


def _process_dep_list(deps: list, source_file: str, section: str, record) -> None:
    """Process a list of PEP 508 dependency strings."""
    for dep_str in deps:
        if not isinstance(dep_str, str):
            continue
        # PEP 508: "package>=1.0,<2.0"
        pkg_name = re.split(r"[>=<!;\[\s]", dep_str)[0].strip().lower()
        _check_package(pkg_name, dep_str, source_file, section, record)


def _process_dep_dict(deps: dict, source_file: str, section: str, record) -> None:
    """Process a dict of {package: version_spec} from Poetry/uv style."""
    for pkg_name, version_spec in deps.items():
        if pkg_name.lower() == "python":
            continue
        version_str = version_spec if isinstance(version_spec, str) else str(version_spec)
        _check_package(
            pkg_name.lower(), f"{pkg_name}={version_str}", source_file, section, record
        )


def _check_package(pkg_name: str, detail: str, source_file: str, section: str, record) -> None:
    """Check if a package name matches a known technology."""
    tech = PACKAGE_NAME_PATTERNS.get(pkg_name)
    if tech:
        record(TechnologyObservation(
            technology=tech,
            signal_type="dependency_declaration",
            source=EvidenceSource(
                file=source_file,
                section=section,
                method="toml_parse",
                pattern=pkg_name,
            ),
            detail=detail,
        ))


def _scan_requirements_files(project_root: Path, record) -> None:
    """Scan requirements*.txt files for known packages."""
    patterns = ["requirements.txt", "requirements-*.txt", "requirements/*.txt"]
    req_files: list[Path] = []
    for pattern in patterns:
        req_files.extend(project_root.glob(pattern))

    for req_path in sorted(req_files):
        rel_path = str(req_path.relative_to(project_root)).replace("\\", "/")
        try:
            for line in req_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                # Handle extras and version specs
                pkg_name = re.split(r"[>=<!;\[\s@]", line)[0].strip().lower()
                if pkg_name:
                    _check_package(pkg_name, line, rel_path, "requirements", record)
        except Exception as e:
            logger.warning(f"Failed to read {req_path}: {e}")


def _scan_package_json(project_root: Path, record) -> None:
    """Scan package.json for frontend dependencies."""
    pkg_path = project_root / "package.json"
    if not pkg_path.exists():
        return

    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to parse package.json: {e}")
        return

    rel_path = "package.json"
    js_tech_patterns = {
        "htmx.org": "HTMX",
        "alpinejs": "Alpine.js",
        "bootstrap": "Bootstrap",
        "tailwindcss": "Tailwind CSS",
        "chart.js": "Chart.js",
        "jquery": "jQuery",
        "react": "React",
        "vue": "Vue.js",
        "svelte": "Svelte",
        "webpack": "Webpack",
        "vite": "Vite",
        "esbuild": "esbuild",
        "typescript": "TypeScript",
        "sass": "Sass/SCSS",
    }

    for section_name in ("dependencies", "devDependencies"):
        section = data.get(section_name, {})
        for pkg_name, version in section.items():
            pkg_lower = pkg_name.lower()
            for pattern, tech in js_tech_patterns.items():
                if pattern in pkg_lower:
                    record(TechnologyObservation(
                        technology=tech,
                        signal_type="dependency_declaration",
                        source=EvidenceSource(
                            file=rel_path,
                            section=section_name,
                            method="json_parse",
                            pattern=pattern,
                        ),
                        detail=f"{pkg_name}@{version}",
                    ))


def _scan_python_imports(project_root: Path, record) -> None:
    """
    Scan Python files for import statements.

    To avoid scanning thousands of files, we scan strategically:
    - Top-level Python files
    - All __init__.py files
    - settings.py files
    - tasks.py files (Celery)
    - A sample of other .py files (up to 50 per subdir)
    """
    from ..constants import EXCLUDED_DIRS

    # Collect files to scan
    scan_targets: list[Path] = []

    # Priority files
    for name in ["settings.py", "tasks.py", "celery.py", "conftest.py", "manage.py"]:
        scan_targets.extend(project_root.rglob(name))

    # All __init__.py in non-excluded dirs
    for p in project_root.rglob("__init__.py"):
        if not _is_excluded_path(p, project_root):
            scan_targets.append(p)

    # Top-level .py files
    for p in project_root.glob("*.py"):
        scan_targets.append(p)

    # A broader rglob sample
    count = 0
    for p in project_root.rglob("*.py"):
        if not _is_excluded_path(p, project_root) and p not in scan_targets:
            scan_targets.append(p)
            count += 1
            if count >= 200:
                break

    # Deduplicate
    scan_targets = list(set(scan_targets))

    # Track what we've already recorded to avoid duplicate signals
    recorded: set[tuple[str, str]] = set()

    for py_file in scan_targets:
        if _is_excluded_path(py_file, project_root):
            continue
        rel_path = str(py_file.relative_to(project_root)).replace("\\", "/")
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
            _extract_imports_from_text(text, rel_path, record, recorded)
        except Exception as e:
            logger.debug(f"Could not read {py_file}: {e}")


def _extract_imports_from_text(
    text: str, rel_path: str, record, recorded: set[tuple[str, str]]
) -> None:
    """Extract import statements from Python source text using regex (fast, safe)."""
    # Match: import X, from X import Y
    import_re = re.compile(
        r"^\s*(?:import|from)\s+([\w.]+)", re.MULTILINE
    )
    for match in import_re.finditer(text):
        module = match.group(1)
        top_level = module.split(".")[0]

        for tech, prefixes in IMPORT_PATTERNS.items():
            for prefix in prefixes:
                if top_level.lower() == prefix.lower() or module.lower().startswith(prefix.lower() + "."):
                    key = (tech, rel_path)
                    if key not in recorded:
                        recorded.add(key)
                        record(TechnologyObservation(
                            technology=tech,
                            signal_type="import_pattern",
                            source=EvidenceSource(
                                file=rel_path,
                                method="regex_import_scan",
                                pattern=f"import {prefix}",
                            ),
                            detail=f"import {module}",
                            confidence=0.9,
                        ))


def _scan_html_patterns(project_root: Path, record) -> None:
    """Scan HTML/template files for frontend technology patterns."""
    from ..constants import EXCLUDED_DIRS

    template_dirs = [
        project_root / "templates",
        project_root / "static",
    ]
    # Also look for any .html files under non-excluded dirs
    html_files: list[Path] = []
    for p in project_root.rglob("*.html"):
        if not _is_excluded_path(p, project_root):
            html_files.append(p)

    recorded: set[tuple[str, str]] = set()

    for html_file in html_files[:100]:  # cap at 100 HTML files
        rel_path = str(html_file.relative_to(project_root)).replace("\\", "/")
        try:
            content = html_file.read_text(encoding="utf-8", errors="replace")
            for tech, pattern in HTML_CONTENT_PATTERNS.items():
                if re.search(pattern, content, re.IGNORECASE):
                    key = (tech, rel_path)
                    if key not in recorded:
                        recorded.add(key)
                        record(TechnologyObservation(
                            technology=tech,
                            signal_type="content_pattern",
                            source=EvidenceSource(
                                file=rel_path,
                                method="html_content_scan",
                                pattern=pattern,
                            ),
                            detail=f"Pattern '{pattern}' matched in {rel_path}",
                            confidence=0.85,
                        ))
        except Exception as e:
            logger.debug(f"Could not read {html_file}: {e}")


def _scan_file_presence(project_root: Path, record) -> None:
    """Detect technologies based on characteristic file presence."""
    file_indicators: list[tuple[str, str, str]] = [
        # (filename or glob, technology, detail)
        ("manage.py", "Django", "manage.py present at project root"),
        ("celery.py", "Celery", "celery.py file found"),
        ("Celeryfile", "Celery", "Celeryfile found"),
        (".flake8", "Flake8", ".flake8 config present"),
        (".ruff.toml", "Ruff", ".ruff.toml config present"),
        ("ruff.toml", "Ruff", "ruff.toml config present"),
        (".mypy.ini", "MyPy", ".mypy.ini config present"),
        ("mypy.ini", "MyPy", "mypy.ini config present"),
        (".pre-commit-config.yaml", "pre-commit", ".pre-commit-config.yaml present"),
        ("Dockerfile", "Docker", "Dockerfile present"),
        ("docker-compose.yml", "Docker Compose", "docker-compose.yml present"),
        ("docker-compose.yaml", "Docker Compose", "docker-compose.yaml present"),
        ("compose.yaml", "Docker Compose", "compose.yaml present"),
        (".github/workflows", "GitHub Actions", ".github/workflows directory present"),
        ("Makefile", "Makefile", "Makefile present"),
    ]

    for indicator, tech, detail in file_indicators:
        target = project_root / indicator
        if target.exists():
            rel_str = str(target.relative_to(project_root)).replace("\\", "/")
            record(TechnologyObservation(
                technology=tech,
                signal_type="file_presence",
                source=EvidenceSource(
                    file=rel_str,
                    method="file_presence",
                ),
                detail=detail,
            ))


def _scan_django_settings(project_root: Path, record) -> None:
    """Scan Django settings.py for specific configurations."""
    settings_patterns: list[Path] = list(project_root.rglob("settings.py"))
    settings_patterns += list(project_root.rglob("settings/*.py"))

    db_patterns = {
        "postgresql": "PostgreSQL",
        "postgres": "PostgreSQL",
        "psycopg": "PostgreSQL/psycopg",
        "sqlite3": "SQLite",
        "mysql": "MySQL",
    }

    for settings_file in settings_patterns[:5]:  # cap
        if _is_excluded_path(settings_file, project_root):
            continue
        rel_path = str(settings_file.relative_to(project_root)).replace("\\", "/")
        try:
            content = settings_file.read_text(encoding="utf-8", errors="replace")

            # Database backend
            for pattern, tech in db_patterns.items():
                if re.search(pattern, content, re.IGNORECASE):
                    record(TechnologyObservation(
                        technology=tech,
                        signal_type="content_pattern",
                        source=EvidenceSource(
                            file=rel_path,
                            section="DATABASES",
                            method="settings_scan",
                            pattern=pattern,
                        ),
                        detail=f"Pattern '{pattern}' found in settings",
                        confidence=0.9,
                    ))

            # Installed apps
            celery_indicators = [
                "django_celery_beat",
                "django_celery_results",
                "celery",
                "CELERY_",
                "BROKER_URL",
                "CELERY_BROKER_URL",
            ]
            for indicator in celery_indicators:
                if indicator in content:
                    record(TechnologyObservation(
                        technology="Celery",
                        signal_type="content_pattern",
                        source=EvidenceSource(
                            file=rel_path,
                            method="settings_scan",
                            pattern=indicator,
                        ),
                        detail=f"'{indicator}' referenced in settings",
                        confidence=0.9,
                    ))
                    break  # one signal per settings file for Celery

            # Cache backend (Redis)
            if re.search(r'redis', content, re.IGNORECASE):
                record(TechnologyObservation(
                    technology="Redis",
                    signal_type="content_pattern",
                    source=EvidenceSource(
                        file=rel_path,
                        section="CACHES or CELERY_BROKER_URL",
                        method="settings_scan",
                        pattern="redis",
                    ),
                    detail="Redis URL or backend referenced in settings",
                    confidence=0.85,
                ))

        except Exception as e:
            logger.debug(f"Could not scan settings {settings_file}: {e}")


def _is_excluded_path(path: Path, project_root: Path) -> bool:
    """Return True if any part of the path relative to project_root is excluded."""
    from ..constants import EXCLUDED_DIRS
    try:
        rel = path.relative_to(project_root)
    except ValueError:
        return False
    return any(part in EXCLUDED_DIRS for part in rel.parts)
