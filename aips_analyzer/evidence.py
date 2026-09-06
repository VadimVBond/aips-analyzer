"""
Evidence builder for AIPS Analyzer.

Accumulates EvidenceItem objects across all analyzers,
assigns sequential IDs (E-001, E-002, ...), and serializes to JSON.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import EvidenceItem, EvidenceReport, EvidenceSource

logger = logging.getLogger(__name__)


class EvidenceBuilder:
    """
    Accumulates evidence items with auto-incrementing IDs.

    Usage:
        builder = EvidenceBuilder()
        builder.add("technology", "Django", "5.2.10",
                    EvidenceSource(file="pyproject.toml", section="dependencies"))
        items = builder.items
    """

    def __init__(self) -> None:
        self._items: list[EvidenceItem] = []
        self._counter: int = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"E-{self._counter:03d}"

    def add(
        self,
        type: str,
        subject: str,
        value: Any,
        source: EvidenceSource | None = None,
        notes: str | None = None,
    ) -> EvidenceItem:
        """Add an evidence item and return it."""
        item = EvidenceItem(
            id=self._next_id(),
            type=type,
            subject=subject,
            value=value,
            source=source or EvidenceSource(),
            notes=notes,
        )
        self._items.append(item)
        return item

    def add_metric(
        self,
        subject: str,
        value: Any,
        source_method: str = "filesystem",
        notes: str | None = None,
    ) -> EvidenceItem:
        """Shorthand for adding a repository metric evidence item."""
        return self.add(
            type="repository_metric",
            subject=subject,
            value=value,
            source=EvidenceSource(method=source_method),
            notes=notes,
        )

    def add_technology(
        self,
        technology: str,
        value: Any,
        source_file: str | None = None,
        source_section: str | None = None,
        source_method: str | None = None,
        source_pattern: str | None = None,
        notes: str | None = None,
    ) -> EvidenceItem:
        """Shorthand for adding a technology observation evidence item."""
        return self.add(
            type="technology",
            subject=technology,
            value=value,
            source=EvidenceSource(
                file=source_file,
                section=source_section,
                method=source_method,
                pattern=source_pattern,
            ),
            notes=notes,
        )

    @property
    def items(self) -> list[EvidenceItem]:
        return list(self._items)

    @property
    def count(self) -> int:
        return self._counter


def serialize_report(report: EvidenceReport, output_path: Path) -> None:
    """
    Write the EvidenceReport to a JSON file.

    Creates parent directories if needed.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(
            data, f, indent=2, ensure_ascii=False, default=_json_default, sort_keys=True
        )
        f.write("\n")

    logger.info(f"Evidence written to {output_path}")


def _json_default(obj: Any) -> Any:
    """JSON serializer for non-standard types."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, set | frozenset):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def build_metrics_list(data: dict[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    """
    Flatten a nested metrics dict into a list of {name, value} records
    suitable for the top-level 'metrics' array in EvidenceReport.
    """
    metrics: list[dict[str, Any]] = []

    def _recurse(d: dict[str, Any], pfx: str) -> None:
        for k, v in d.items():
            key = f"{pfx}.{k}" if pfx else k
            if isinstance(v, dict):
                _recurse(v, key)
            elif isinstance(v, int | float | str | bool):
                metrics.append({"name": key, "value": v})

    _recurse(data, prefix)
    return metrics
