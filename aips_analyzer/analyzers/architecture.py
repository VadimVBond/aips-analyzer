"""
Analyzer #6 — Basic Architecture (AST-based)

Analyzes Python project structure using Python's built-in ast module.
Does NOT import or execute analyzed project code.

Collects:
- Packages and modules map
- Import graph (internal vs external)
- Django apps structure
- Celery tasks
- Models / Views / URLs presence
- Cyclic dependencies
- High fan-in / fan-out modules
- Unusually large modules
"""

from __future__ import annotations

import ast
import logging
from collections import defaultdict
from pathlib import Path
from typing import Generator

from ..constants import EXCLUDED_DIRS, MIGRATION_DIR_NAMES
from ..evidence import EvidenceBuilder
from ..models import AnalyzerResult, AnalyzerWarning, ArchitectureModule, EvidenceSource

logger = logging.getLogger(__name__)

# Thresholds for candidate findings
FAN_IN_THRESHOLD = 5  # modules that import this one ≥ threshold
FAN_OUT_THRESHOLD = 15  # this module imports ≥ threshold others
LARGE_MODULE_THRESHOLD = 500  # lines


def run(project_root: Path, evidence: EvidenceBuilder) -> AnalyzerResult:
    result = AnalyzerResult(name="architecture")

    try:
        data = _analyze_architecture(project_root, evidence)
        result.data = data
    except Exception as exc:
        logger.exception("Architecture analyzer failed")
        result.success = False
        result.warnings.append(
            AnalyzerWarning(analyzer="architecture", error=str(exc), recoverable=False)
        )

    return result


def _analyze_architecture(project_root: Path, evidence: EvidenceBuilder) -> dict:
    """Main architecture analysis using AST."""

    # Step 1: Discover all Python modules
    modules: list[ArchitectureModule] = []
    for py_file in _iter_python_files(project_root):
        module = _analyze_python_file(py_file, project_root)
        if module:
            modules.append(module)

    # Step 2: Build internal import graph
    module_packages = {m.package for m in modules}
    _classify_imports(modules, module_packages)

    # Step 3: Build adjacency for cycle detection and fan metrics
    graph: dict[str, set[str]] = defaultdict(set)
    for module in modules:
        for imp in module.imports_internal:
            graph[module.package].add(imp)

    # Step 4: Detect cycles
    cycles = _find_cycles(graph)

    # Step 5: Fan-in / fan-out
    fan_out: dict[str, int] = {m.package: len(m.imports_internal) for m in modules}
    fan_in: dict[str, int] = defaultdict(int)
    for m in modules:
        for imp in m.imports_internal:
            fan_in[imp] += 1

    high_fan_out = [
        {"module": pkg, "fan_out": cnt}
        for pkg, cnt in sorted(fan_out.items(), key=lambda x: -x[1])
        if cnt >= FAN_OUT_THRESHOLD
    ]
    high_fan_in = [
        {"module": pkg, "fan_in": cnt}
        for pkg, cnt in sorted(fan_in.items(), key=lambda x: -x[1])
        if cnt >= FAN_IN_THRESHOLD
    ]

    # Step 6: Large modules
    large_modules = [
        {"module": m.package, "file": m.path, "lines": m.lines}
        for m in modules
        if m.lines >= LARGE_MODULE_THRESHOLD
    ]

    # Step 7: Django-specific structure
    django_apps = _find_django_apps(modules, project_root)
    celery_tasks = [m for m in modules if m.has_tasks]
    model_modules = [m for m in modules if m.has_models]
    view_modules = [m for m in modules if m.has_views]
    url_modules = [m for m in modules if m.has_urls]

    # Step 8: External imports summary
    external_pkgs: dict[str, int] = defaultdict(int)
    for m in modules:
        for imp in m.imports_external:
            top = imp.split(".")[0]
            external_pkgs[top] += 1
    top_external = sorted(external_pkgs.items(), key=lambda x: -x[1])[:30]

    # Step 9: Parse errors
    parse_errors = [
        {"file": m.path, "error": m.parse_error} for m in modules if m.parse_error
    ]

    # Emit evidence
    evidence.add_metric("python_modules_parsed", len(modules))
    evidence.add_metric("python_modules_with_parse_errors", len(parse_errors))
    evidence.add_metric("cyclic_dependencies_found", len(cycles))
    evidence.add_metric("high_fan_out_modules", len(high_fan_out))
    evidence.add_metric("high_fan_in_modules", len(high_fan_in))
    evidence.add_metric("django_apps_found_ast", len(django_apps))
    evidence.add_metric("celery_task_modules", len(celery_tasks))
    evidence.add_metric("model_modules", len(model_modules))
    evidence.add_metric("view_modules", len(view_modules))

    if cycles:
        evidence.add(
            type="architecture",
            subject="cyclic_dependencies",
            value=cycles[:10],
            source=EvidenceSource(method="ast_import_graph"),
            notes="Cyclic import dependencies detected",
        )

    return {
        "total_modules": len(modules),
        "packages": _count_packages(modules),
        "django_apps": [
            {
                "name": app["name"],
                "path": app["path"],
                "has_models": app["has_models"],
                "has_views": app["has_views"],
                "has_urls": app["has_urls"],
                "has_tasks": app["has_tasks"],
                "has_admin": app["has_admin"],
            }
            for app in django_apps
        ],
        "modules_map": [m.to_dict() for m in modules[:200]],  # cap for JSON size
        "total_modules_in_map": len(modules),
        "model_modules": [m.path for m in model_modules],
        "view_modules": [m.path for m in view_modules],
        "url_modules": [m.path for m in url_modules],
        "celery_task_modules": [m.path for m in celery_tasks],
        "cyclic_dependencies": {
            "count": len(cycles),
            "cycles": cycles[:20],  # cap
        },
        "candidate_findings": {
            "high_fan_out_modules": high_fan_out[:20],
            "high_fan_in_modules": high_fan_in[:20],
            "large_modules": sorted(large_modules, key=lambda x: -x["lines"])[:20],
        },
        "top_external_imports": [
            {"package": pkg, "import_count": cnt} for pkg, cnt in top_external
        ],
        "parse_errors": parse_errors[:50],
        "thresholds": {
            "fan_in": FAN_IN_THRESHOLD,
            "fan_out": FAN_OUT_THRESHOLD,
            "large_module_lines": LARGE_MODULE_THRESHOLD,
        },
        "note": "candidate_findings are observations based on metrics thresholds, not final architectural verdicts",
    }


def _iter_python_files(project_root: Path) -> Generator[Path, None, None]:
    """Yield .py files, skipping excluded directories and migrations.

    Results are sorted alphabetically for deterministic evidence ID ordering.
    """
    py_files: list[Path] = []
    for path in project_root.rglob("*.py"):
        rel = path.relative_to(project_root)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if any(part in MIGRATION_DIR_NAMES for part in rel.parts):
            continue
        py_files.append(path)
    for path in sorted(py_files, key=lambda p: str(p)):
        yield path


def _analyze_python_file(
    py_file: Path, project_root: Path
) -> ArchitectureModule | None:
    """Parse a Python file with AST and extract structural information."""
    rel_path = str(py_file.relative_to(project_root)).replace("\\", "/")

    # Build dot-notation package name
    parts = list(py_file.relative_to(project_root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    package = ".".join(parts)

    module = ArchitectureModule(path=rel_path, package=package)

    try:
        source = py_file.read_text(encoding="utf-8", errors="replace")
        module.lines = len(source.splitlines())
    except Exception as e:
        module.parse_error = f"Read error: {e}"
        return module

    # Determine flags from filename/path
    stem = py_file.stem.lower()
    rel_str = rel_path.lower()
    if stem == "models" or stem.startswith("model"):
        module.has_models = True
    if stem in ("views", "viewsets", "view"):
        module.has_views = True
    if stem in ("urls", "url"):
        module.has_urls = True
    if stem in ("tasks", "celery_tasks"):
        module.has_tasks = True
    if stem == "admin":
        module.has_admin = True
    if any(
        p.lower().startswith("test") or p.lower().endswith("test")
        for p in rel_path.split("/")
    ):
        module.is_test = True

    # Parse AST
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as e:
        module.parse_error = f"SyntaxError: {e}"
        return module
    except Exception as e:
        module.parse_error = f"ParseError: {e}"
        return module

    # Walk AST
    all_imports: list[str] = []
    class_names: list[str] = []
    func_names: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                all_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                all_imports.append(node.module)
        elif isinstance(node, ast.ClassDef):
            class_names.append(node.name)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            # Only top-level functions
            func_names.append(node.name)

    # Check for Celery task decorators
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Attribute):
                    if decorator.attr in ("task", "shared_task"):
                        module.has_tasks = True
                elif isinstance(decorator, ast.Name):
                    if decorator.id in ("task", "shared_task"):
                        module.has_tasks = True

    # Check for Django model/view class inheritance patterns
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_str = ast.unparse(base) if hasattr(ast, "unparse") else ""
                if any(x in base_str for x in ["Model", "models.Model"]):
                    module.has_models = True
                if any(
                    x in base_str for x in ["View", "APIView", "ViewSet", "ListView"]
                ):
                    module.has_views = True

    module.classes = class_names[:50]  # cap
    module.functions = func_names[:50]  # cap

    # Store raw imports — will be classified later
    module.imports_external = all_imports  # temp: will be reclassified

    return module


def _classify_imports(
    modules: list[ArchitectureModule], known_packages: set[str]
) -> None:
    """
    Separate imports into internal (within project) and external (third-party/stdlib).
    Updates modules in-place.
    """
    # Build a set of top-level package names used in the project
    top_level_packages = set()
    for pkg in known_packages:
        top = pkg.split(".")[0]
        top_level_packages.add(top)

    import sys

    stdlib_modules = (
        sys.stdlib_module_names if hasattr(sys, "stdlib_module_names") else set()
    )

    for module in modules:
        internal: list[str] = []
        external: list[str] = []
        for imp in module.imports_external:
            top = imp.split(".")[0]
            if top in top_level_packages and top not in stdlib_modules:
                internal.append(imp)
            else:
                external.append(imp)
        module.imports_internal = internal
        module.imports_external = external


def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """
    Detect cyclic dependencies in the import graph using DFS.
    Returns list of cycles (each cycle is a list of module names).
    """
    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def dfs(node: str, path: list[str]) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in graph.get(node, set()):
            if neighbor not in visited:
                dfs(neighbor, path)
            elif neighbor in rec_stack:
                # Found cycle — extract it
                try:
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    if cycle not in cycles and len(cycles) < 50:
                        cycles.append(cycle)
                except ValueError:
                    pass

        path.pop()
        rec_stack.discard(node)

    for node in list(graph.keys()):
        if node not in visited:
            dfs(node, [])

    return cycles


def _find_django_apps(
    modules: list[ArchitectureModule], project_root: Path
) -> list[dict]:
    """
    Group modules by their parent directory and determine if it looks like a Django app.
    """
    app_dirs: dict[str, dict] = {}

    for module in modules:
        parts = module.path.split("/")
        if len(parts) < 2:
            continue
        # The first directory containing Python files is a candidate app
        parent = parts[0]
        if parent not in app_dirs:
            app_dirs[parent] = {
                "name": parent,
                "path": parent,
                "has_models": False,
                "has_views": False,
                "has_urls": False,
                "has_tasks": False,
                "has_admin": False,
                "module_count": 0,
            }
        app_dirs[parent]["module_count"] += 1
        if module.has_models:
            app_dirs[parent]["has_models"] = True
        if module.has_views:
            app_dirs[parent]["has_views"] = True
        if module.has_urls:
            app_dirs[parent]["has_urls"] = True
        if module.has_tasks:
            app_dirs[parent]["has_tasks"] = True
        if module.has_admin:
            app_dirs[parent]["has_admin"] = True

    # Filter: a Django app must have at least models or views
    django_apps = [
        app
        for app in app_dirs.values()
        if (app["has_models"] or app["has_views"]) and app["module_count"] >= 1
    ]

    return django_apps


def _count_packages(modules: list[ArchitectureModule]) -> dict[str, int]:
    """Count modules per top-level package."""
    counts: dict[str, int] = defaultdict(int)
    for m in modules:
        top = m.package.split(".")[0] if m.package else "root"
        counts[top] += 1
    return dict(sorted(counts.items()))
