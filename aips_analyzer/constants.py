"""
Centralized constants for AIPS Analyzer.

All exclusion lists and file type mappings are defined here
so they can be updated in one place and reused across all analyzers.
"""

from typing import FrozenSet

# ─── Directories to exclude from all analysis ──────────────────────────────

EXCLUDED_DIRS: FrozenSet[str] = frozenset(
    [
        ".git",
        ".venv",
        "venv",
        "env",
        ".env",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "coverage",
        "htmlcov",
        "dist",
        "build",
        ".eggs",
        "*.egg-info",
        ".cache",
        ".turbo",
        "gh-pages",
    ]
)

# ─── File extension → language/type mapping ────────────────────────────────

EXTENSION_MAP: dict[str, str] = {
    # Python
    ".py": "python",
    ".pyi": "python_stub",
    ".pyw": "python",
    # Web
    ".html": "html",
    ".htm": "html",
    ".jinja": "html_template",
    ".jinja2": "html_template",
    ".j2": "html_template",
    # Styles
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    # JavaScript / TypeScript
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    # Data / Config
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "cfg",
    ".env": "dotenv",
    # Documentation
    ".md": "markdown",
    ".rst": "rst",
    ".txt": "text",
    # SQL / Data
    ".sql": "sql",
    # Shell
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".bat": "batch",
    ".ps1": "powershell",
    # Docker / CI
    ".dockerfile": "dockerfile",
    # Locks
    ".lock": "lockfile",
}

# Specific filenames that map to a type (for files without extensions or special names)
FILENAME_MAP: dict[str, str] = {
    "dockerfile": "dockerfile",
    "makefile": "makefile",
    ".gitignore": "gitignore",
    ".gitattributes": "gitattributes",
    ".editorconfig": "editorconfig",
    "procfile": "procfile",
    ".env": "dotenv",
    ".flake8": "linter_config",
    "manage.py": "django_manage",
    "conftest.py": "pytest_conftest",
    "setup.cfg": "setup_cfg",
    "setup.py": "setup_py",
}

# ─── Dependency file names ─────────────────────────────────────────────────

PYTHON_DEPENDENCY_FILES: tuple[str, ...] = (
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-prod.txt",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
    "setup.cfg",
    "setup.py",
)

NODE_DEPENDENCY_FILES: tuple[str, ...] = (
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
)

# ─── Django-specific patterns ──────────────────────────────────────────────

DJANGO_APP_INDICATORS: tuple[str, ...] = (
    "models.py",
    "views.py",
    "urls.py",
    "admin.py",
    "apps.py",
    "migrations",
)

DJANGO_PROJECT_INDICATORS: tuple[str, ...] = (
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "settings.py",
)

# ─── Test file patterns ────────────────────────────────────────────────────

TEST_FILE_PREFIXES: tuple[str, ...] = ("test_", "tests_")
TEST_FILE_SUFFIXES: tuple[str, ...] = ("_test", "_spec")
TEST_DIR_NAMES: frozenset[str] = frozenset(["tests", "test", "spec"])

# ─── Migration dir names ───────────────────────────────────────────────────

MIGRATION_DIR_NAMES: frozenset[str] = frozenset(["migrations", "migration"])
