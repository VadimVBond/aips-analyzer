"""
Data models for AIPS Analyzer.

Uses Python dataclasses for simplicity — no external dependencies required.
All models are designed to be JSON-serializable.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any


# ─── Evidence ──────────────────────────────────────────────────────────────


@dataclass
class EvidenceSource:
    """Provenance information for an evidence item."""

    file: str | None = None  # relative path inside project
    section: str | None = None  # e.g. "dependencies", "devDependencies"
    line: int | None = None  # line number if applicable
    method: str | None = None  # e.g. "ast_import", "file_presence", "content_match"
    pattern: str | None = None  # regexp or keyword that triggered detection

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


@dataclass
class EvidenceItem:
    """
    A single atomic piece of evidence about a project.

    Evidence is raw observation — not a conclusion or verdict.
    Example: Django found in pyproject.toml -> [dependencies] section.
    """

    id: str  # E-001, E-002, ...
    type: str  # "technology", "dependency", "repository_metric", "git", "architecture"
    subject: str  # what was observed: "Django", "python_files", "celery_task", ...
    value: Any  # the observed value (str, int, dict, list, bool)
    source: EvidenceSource = field(default_factory=EvidenceSource)
    notes: str | None = None  # optional human-readable note

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "subject": self.subject,
            "value": self.value,
            "source": self.source.to_dict(),
        }
        if self.notes:
            d["notes"] = self.notes
        return d


# ─── Analyzer Warning ──────────────────────────────────────────────────────


@dataclass
class AnalyzerWarning:
    """A non-fatal issue encountered during analysis."""

    analyzer: str
    error: str
    recoverable: bool = True
    details: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "analyzer": self.analyzer,
            "error": self.error,
            "recoverable": self.recoverable,
        }
        if self.details:
            d["details"] = self.details
        return d


# ─── Analyzer Result ───────────────────────────────────────────────────────


@dataclass
class AnalyzerResult:
    """
    Result of a single analyzer module.

    Each analyzer returns structured data + evidence items + optional warnings.
    """

    name: str
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[EvidenceItem] = field(default_factory=list)
    warnings: list[AnalyzerWarning] = field(default_factory=list)
    success: bool = True


# ─── Technology Observation ────────────────────────────────────────────────


@dataclass
class TechnologyObservation:
    """
    An observed technology signal.

    Does NOT claim "framework = Django".
    Instead records: "Django signal observed via pyproject.toml [dependencies]".
    """

    technology: str
    signal_type: str  # "file_presence", "dependency_declaration", "import_pattern",
    #                    "content_match", "directory_structure"
    source: EvidenceSource = field(default_factory=EvidenceSource)
    detail: str | None = None  # e.g. "version: 5.2.10" or "import django.db"
    confidence: float = 1.0  # 0.0-1.0, only set to <1.0 for ambiguous signals

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "technology": self.technology,
            "signal_type": self.signal_type,
            "source": self.source.to_dict(),
            "confidence": self.confidence,
        }
        if self.detail:
            d["detail"] = self.detail
        return d


# ─── Dependency Entry ──────────────────────────────────────────────────────


@dataclass
class DependencyEntry:
    """A single dependency from a dependency file."""

    name: str
    version_spec: str | None = None  # e.g. ">=5.2,<6.0", "^5.2.10"
    resolved_version: str | None = None  # from lockfile if available
    is_dev: bool = False
    source_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name}
        if self.version_spec:
            d["version_spec"] = self.version_spec
        if self.resolved_version:
            d["resolved_version"] = self.resolved_version
        if self.is_dev:
            d["is_dev"] = True
        if self.source_file:
            d["source_file"] = self.source_file
        return d


# ─── Architecture Module ───────────────────────────────────────────────────


@dataclass
class ArchitectureModule:
    """A Python module discovered via AST analysis."""

    path: str  # relative path from project root
    package: str  # dot-notation package name
    lines: int = 0
    imports_internal: list[str] = field(default_factory=list)
    imports_external: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    has_models: bool = False
    has_views: bool = False
    has_urls: bool = False
    has_tasks: bool = False  # Celery tasks
    has_admin: bool = False
    is_test: bool = False
    is_migration: bool = False
    parse_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in dataclasses.asdict(self).items() if v not in (None, [], False, 0)}


# ─── Full Evidence Report ──────────────────────────────────────────────────


@dataclass
class EvidenceReport:
    """The final top-level output of the analyzer."""

    schema: str = "aips-evidence/v1"
    analyzer: dict[str, str] = field(
        default_factory=lambda: {"name": "aips-analyzer", "version": "0.1.0"}
    )
    project: dict[str, Any] = field(default_factory=dict)
    discovery: dict[str, Any] = field(default_factory=dict)
    technology: dict[str, Any] = field(default_factory=dict)
    repository: dict[str, Any] = field(default_factory=dict)
    dependencies: dict[str, Any] = field(default_factory=dict)
    git: dict[str, Any] = field(default_factory=dict)
    architecture: dict[str, Any] = field(default_factory=dict)
    evidence: list[EvidenceItem] = field(default_factory=list)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[AnalyzerWarning] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "analyzer": self.analyzer,
            "project": self.project,
            "discovery": self.discovery,
            "technology": self.technology,
            "repository": self.repository,
            "dependencies": self.dependencies,
            "git": self.git,
            "architecture": self.architecture,
            "evidence": [e.to_dict() for e in self.evidence],
            "metrics": self.metrics,
            "warnings": [w.to_dict() for w in self.warnings],
        }
