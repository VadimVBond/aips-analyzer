"""
Analyzer #4 — Dependencies

Parses dependency files WITHOUT executing any code:
- pyproject.toml (PEP 621, Poetry, PDM, Hatch, uv)
- requirements*.txt
- Pipfile
- package.json / package-lock.json
- Detects lockfile presence
- Records package manager used
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

from ..evidence import EvidenceBuilder
from ..models import AnalyzerResult, AnalyzerWarning, DependencyEntry, EvidenceSource

logger = logging.getLogger(__name__)


def run(project_root: Path, evidence: EvidenceBuilder) -> AnalyzerResult:
    result = AnalyzerResult(name="dependencies")

    try:
        data = _analyze_dependencies(project_root, evidence)
        result.data = data
    except Exception as exc:
        logger.exception("Dependencies analyzer failed")
        result.success = False
        result.warnings.append(
            AnalyzerWarning(analyzer="dependencies", error=str(exc), recoverable=False)
        )

    return result


def _analyze_dependencies(project_root: Path, evidence: EvidenceBuilder) -> dict:
    python_result = _analyze_python_deps(project_root, evidence)
    node_result = _analyze_node_deps(project_root, evidence)

    # Overall summary
    total_deps = (
        python_result.get("production_count", 0)
        + python_result.get("dev_count", 0)
        + node_result.get("production_count", 0)
        + node_result.get("dev_count", 0)
    )

    return {
        "python": python_result,
        "node": node_result,
        "total_dependencies": total_deps,
    }


# ─── Python ────────────────────────────────────────────────────────────────

def _analyze_python_deps(project_root: Path, evidence: EvidenceBuilder) -> dict:
    """Parse Python dependency files in order of preference."""
    result: dict = {
        "package_manager": None,
        "source_files": [],
        "lockfile_present": False,
        "lockfile_file": None,
        "production": [],
        "dev": [],
        "production_count": 0,
        "dev_count": 0,
    }

    # Detect lockfiles
    for lockfile in ["uv.lock", "poetry.lock", "Pipfile.lock"]:
        if (project_root / lockfile).exists():
            result["lockfile_present"] = True
            result["lockfile_file"] = lockfile
            evidence.add(
                type="dependency",
                subject="lockfile_presence",
                value=lockfile,
                source=EvidenceSource(file=lockfile, method="file_presence"),
                notes=f"Lockfile {lockfile} found — reproducible builds possible",
            )
            break

    # Try pyproject.toml
    pyproject_path = project_root / "pyproject.toml"
    if pyproject_path.exists():
        pm, prod, dev = _parse_pyproject(pyproject_path, project_root)
        if pm:
            result["package_manager"] = pm
        result["source_files"].append("pyproject.toml")
        result["production"].extend([d.to_dict() for d in prod])
        result["dev"].extend([d.to_dict() for d in dev])
        result["production_count"] += len(prod)
        result["dev_count"] += len(dev)

        evidence.add(
            type="dependency",
            subject="python_package_manager",
            value=pm or "unknown (pyproject.toml found)",
            source=EvidenceSource(file="pyproject.toml", method="file_parse"),
        )

    # Try requirements.txt files
    req_files = list(project_root.glob("requirements*.txt")) + list(
        (project_root / "requirements").glob("*.txt")
        if (project_root / "requirements").is_dir()
        else []
    )

    for req_file in sorted(req_files):
        rel = str(req_file.relative_to(project_root)).replace("\\", "/")
        deps = _parse_requirements_txt(req_file, rel)
        is_dev = any(x in rel.lower() for x in ["dev", "test", "local"])

        result["source_files"].append(rel)
        for dep in deps:
            dep_dict = dep.to_dict()
            if is_dev:
                result["dev"].append(dep_dict)
                result["dev_count"] += 1
            else:
                result["production"].append(dep_dict)
                result["production_count"] += 1

        if not result["package_manager"]:
            result["package_manager"] = "pip/requirements.txt"

        evidence.add(
            type="dependency",
            subject="requirements_file",
            value={"file": rel, "count": len(deps)},
            source=EvidenceSource(file=rel, method="file_parse"),
        )

    # Pipfile
    pipfile = project_root / "Pipfile"
    if pipfile.exists() and not result["source_files"]:
        result["source_files"].append("Pipfile")
        result["package_manager"] = "pipenv"
        prod, dev = _parse_pipfile(pipfile)
        result["production"].extend([d.to_dict() for d in prod])
        result["dev"].extend([d.to_dict() for d in dev])
        result["production_count"] += len(prod)
        result["dev_count"] += len(dev)

    # Emit summary metrics
    evidence.add_metric(
        "python_production_deps", result["production_count"],
        notes="Count of production Python dependencies"
    )
    evidence.add_metric(
        "python_dev_deps", result["dev_count"],
        notes="Count of dev Python dependencies"
    )

    return result


def _parse_pyproject(path: Path, project_root: Path) -> tuple[str | None, list[DependencyEntry], list[DependencyEntry]]:
    """Parse pyproject.toml and return (package_manager, prod_deps, dev_deps)."""
    pm = None
    prod: list[DependencyEntry] = []
    dev: list[DependencyEntry] = []

    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomllib
            except ImportError:
                try:
                    import tomli as tomllib  # type: ignore
                except ImportError:
                    logger.warning("tomllib/tomli not available, falling back to text scan")
                    return None, [], []

        content = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to parse pyproject.toml: {e}")
        return None, [], []

    # PEP 621 [project.dependencies]
    project_section = content.get("project", {})
    if project_section:
        for dep_str in project_section.get("dependencies", []):
            entry = _parse_pep508(dep_str, "pyproject.toml")
            if entry:
                prod.append(entry)

        for group, deps in project_section.get("optional-dependencies", {}).items():
            is_dev = any(x in group.lower() for x in ["dev", "test", "lint", "ci"])
            for dep_str in deps:
                entry = _parse_pep508(dep_str, "pyproject.toml")
                if entry:
                    entry.is_dev = is_dev
                    (dev if is_dev else prod).append(entry)

    # Poetry [tool.poetry]
    poetry = content.get("tool", {}).get("poetry", {})
    if poetry:
        pm = "poetry"
        for name, spec in poetry.get("dependencies", {}).items():
            if name.lower() == "python":
                continue
            version = spec if isinstance(spec, str) else str(spec)
            prod.append(DependencyEntry(name=name, version_spec=version, source_file="pyproject.toml"))

        for name, spec in poetry.get("dev-dependencies", {}).items():
            version = spec if isinstance(spec, str) else str(spec)
            dev.append(DependencyEntry(name=name, version_spec=version, is_dev=True, source_file="pyproject.toml"))

        # Poetry groups
        for group_name, group_data in poetry.get("group", {}).items():
            is_dev_group = any(x in group_name.lower() for x in ["dev", "test"])
            for name, spec in group_data.get("dependencies", {}).items():
                version = spec if isinstance(spec, str) else str(spec)
                entry = DependencyEntry(name=name, version_spec=version, is_dev=is_dev_group, source_file="pyproject.toml")
                (dev if is_dev_group else prod).append(entry)

    # uv [tool.uv.dev-dependencies]
    uv = content.get("tool", {}).get("uv", {})
    if uv:
        if not pm:
            pm = "uv"
        for dep_str in uv.get("dev-dependencies", []):
            entry = _parse_pep508(dep_str, "pyproject.toml")
            if entry:
                entry.is_dev = True
                dev.append(entry)

    # Hatch [tool.hatch.envs]
    if not pm and content.get("tool", {}).get("hatch"):
        pm = "hatch"

    # Build system detection
    build_backend = content.get("build-system", {}).get("build-backend", "")
    if not pm:
        if "poetry" in build_backend:
            pm = "poetry"
        elif "hatchling" in build_backend:
            pm = "hatch"
        elif "setuptools" in build_backend or "flit" in build_backend:
            pm = "pip/setuptools"

    return pm, prod, dev


def _parse_pep508(dep_str: str, source_file: str) -> DependencyEntry | None:
    """Parse a PEP 508 dependency string into a DependencyEntry."""
    if not dep_str or not isinstance(dep_str, str):
        return None
    # Extract name and version spec
    match = re.match(r"^([A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?)\s*([>=<!;\[\s@].*)?$", dep_str.strip())
    if not match:
        return None
    name = match.group(1)
    spec = match.group(3) or None
    if spec:
        # Remove extras and env markers for cleanliness
        spec = re.split(r";", spec)[0].strip()
    return DependencyEntry(name=name, version_spec=spec, source_file=source_file)


def _parse_requirements_txt(path: Path, rel_path: str) -> list[DependencyEntry]:
    """Parse a requirements.txt file."""
    deps: list[DependencyEntry] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-r") or line.startswith("-c"):
                continue
            if line.startswith("-"):
                continue  # skip -i, --index-url, etc.
            # Remove inline comments
            line = line.split("#")[0].strip()
            if not line:
                continue
            entry = _parse_pep508(line, rel_path)
            if entry:
                deps.append(entry)
    except Exception as e:
        logger.warning(f"Failed to read {path}: {e}")
    return deps


def _parse_pipfile(path: Path) -> tuple[list[DependencyEntry], list[DependencyEntry]]:
    """Parse a Pipfile (TOML format)."""
    prod: list[DependencyEntry] = []
    dev: list[DependencyEntry] = []
    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomllib
            except ImportError:
                return prod, dev

        content = tomllib.loads(path.read_text(encoding="utf-8"))
        for name, spec in content.get("packages", {}).items():
            version = spec if isinstance(spec, str) else "*"
            prod.append(DependencyEntry(name=name, version_spec=version, source_file="Pipfile"))
        for name, spec in content.get("dev-packages", {}).items():
            version = spec if isinstance(spec, str) else "*"
            dev.append(DependencyEntry(name=name, version_spec=version, is_dev=True, source_file="Pipfile"))
    except Exception as e:
        logger.warning(f"Failed to parse Pipfile: {e}")
    return prod, dev


# ─── Node / JavaScript ─────────────────────────────────────────────────────

def _analyze_node_deps(project_root: Path, evidence: EvidenceBuilder) -> dict:
    """Analyze Node.js dependencies."""
    result: dict = {
        "package_manager": None,
        "source_files": [],
        "lockfile_present": False,
        "lockfile_file": None,
        "production": [],
        "dev": [],
        "production_count": 0,
        "dev_count": 0,
    }

    # Detect package manager from lockfile
    for lockfile, pm_name in [
        ("package-lock.json", "npm"),
        ("yarn.lock", "yarn"),
        ("pnpm-lock.yaml", "pnpm"),
        ("bun.lockb", "bun"),
    ]:
        if (project_root / lockfile).exists():
            result["lockfile_present"] = True
            result["lockfile_file"] = lockfile
            result["package_manager"] = pm_name
            evidence.add(
                type="dependency",
                subject="node_lockfile_presence",
                value=lockfile,
                source=EvidenceSource(file=lockfile, method="file_presence"),
            )
            break

    pkg_json = project_root / "package.json"
    if not pkg_json.exists():
        return result

    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to parse package.json: {e}")
        return result

    result["source_files"].append("package.json")
    if not result["package_manager"]:
        result["package_manager"] = data.get("packageManager", "npm")

    for name, version in data.get("dependencies", {}).items():
        result["production"].append({"name": name, "version_spec": version, "is_dev": False})
        result["production_count"] += 1

    for name, version in data.get("devDependencies", {}).items():
        result["dev"].append({"name": name, "version_spec": version, "is_dev": True})
        result["dev_count"] += 1

    evidence.add_metric("node_production_deps", result["production_count"])
    evidence.add_metric("node_dev_deps", result["dev_count"])

    return result
