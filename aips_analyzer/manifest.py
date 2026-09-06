"""
AIPS Analyzer — Manifest writer.

Produces a deterministic `manifest.json` describing the analysis
package for a target project.

Manifest is a portable description of what was produced, not
where it was produced. Local paths are kept only for diagnostic
purposes (per AA-019 §4: "Portable artifacts must NOT depend on
absolute local paths").
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

MANIFEST_SCHEMA = "aips-manifest/v1"
MANIFEST_VERSION = "0.1.0"

# Volatile keys that are intentionally non-deterministic.
# sha256 in the manifest is computed from deterministic reconstruction
# (these fields stripped) so that two runs of the same analyzer
# version against the same project state produce identical manifest
# artifact hashes. Per AA-019 §5.
_VOLATILE_KEYS: set[str] = {
    "analyzed_at",
    "analysis_duration_seconds",
    "output_file",
    "first_commit_date",
    "latest_commit_date",
}

# Lines in evidence-audit.md that are volatile (contain timestamps).
_AUDIT_VOLATILE_RE = re.compile(
    r"(generated at|audit generated at|analyzed at): .+",
    re.IGNORECASE,
)


def _strip_volatile_for_hash(obj) -> str:
    """
    Return a canonical JSON string suitable for deterministic hashing.

    Removes volatile keys and sorts keys, producing identical output
    across runs for the same semantic content.
    """
    return json.dumps(
        _strip_volatile(obj),
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def _strip_volatile(obj):
    """Recursively strip volatile keys from a JSON-serializable object."""
    if isinstance(obj, dict):
        return {
            k: _strip_volatile(v) for k, v in obj.items() if k not in _VOLATILE_KEYS
        }
    if isinstance(obj, list):
        return [_strip_volatile(x) for x in obj]
    return obj


def _sha256_of_deterministic_content(path: Path) -> str:
    """
    Compute SHA-256 of the deterministic (volatile-stripped) content
    of a JSON or markdown file.

    For JSON: parses, strips volatile keys, re-serializes canonically,
    then hashes. This ensures the manifest hash is stable across runs
    even when volatile timestamps differ.
    """
    raw = path.read_bytes()

    if path.suffix.lower() == ".json":
        try:
            data = json.loads(raw.decode("utf-8"))
            canonical = _strip_volatile_for_hash(data)
            h = hashlib.sha256()
            h.update(canonical.encode("utf-8"))
            return h.hexdigest()
        except (ValueError, UnicodeDecodeError):
            # Fall back to raw bytes hash if JSON is malformed.
            h = hashlib.sha256()
            h.update(raw)
            return h.hexdigest()
    elif path.suffix.lower() == ".md":
        # Strip lines containing volatile timestamps, then hash.
        lines = raw.decode("utf-8").splitlines()
        stable_lines = [
            line for line in lines if not _AUDIT_VOLATILE_RE.search(line.strip())
        ]
        stable_text = "\n".join(stable_lines).strip() + "\n"
        h = hashlib.sha256()
        h.update(stable_text.encode("utf-8"))
        return h.hexdigest()
    else:
        # Binary or unknown: hash raw bytes.
        h = hashlib.sha256()
        h.update(raw)
        return h.hexdigest()


def _file_sha256(path: Path) -> str:
    """Alias for external callers."""
    return _sha256_of_deterministic_content(path)


def _relative_path(path: Path, base: Path) -> str:
    """Portable path: try to make relative to base, else return filename only.

    Per AA-019 §4, portable artifacts must not depend on absolute paths.
    """
    try:
        rel = path.relative_to(base)
        return str(rel).replace("\\", "/")
    except ValueError:
        return path.name


def write_manifest(
    package_dir: Path,
    project_name: str,
    analyzer_version: str = __version__,
    aips_evidence_schema: str = "aips-evidence/v1",
    aips_evidence_audit_schema: str = "aips-evidence-audit/v1",
    aips_evidence_audit_v2_schema: str = "aips-evidence-audit/v2",
    aips_ai_context_schema: str = "aips-ai-context/v1",
    analyzed_at: str | None = None,
) -> dict:
    """Write deterministic manifest.json for the analysis package.

    Parameters
    ----------
    package_dir : Path
        Directory containing all artifacts (typically
        output/<project_name>/).
    project_name : str
        Project name (e.g. "freelance_pulse").
    analyzer_version : str
        AIPS Analyzer version (e.g. "0.1.0").
    aips_evidence_schema : str
        Schema identifier for the raw evidence.
    aips_evidence_audit_schema : str
        Schema identifier for the v1 audit summary.
    aips_evidence_audit_v2_schema : str
        Schema identifier for the v2 aggregator output.
    aips_ai_context_schema : str
        Schema identifier for the AI Context.
    analyzed_at : str | None
        ISO-8601 timestamp. If None, generated at call time. Per AA-019 §4,
        timestamps are explicitly classified as non-deterministic
        metadata; the deterministic core does not include them.

    Returns
    -------
    dict
        The manifest content (also written to package_dir/manifest.json).
    """
    package_dir = Path(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    if analyzed_at is None:
        analyzed_at = datetime.now(timezone.utc).isoformat()

    # Discover all artifacts (only files that exist).
    artifact_specs = [
        ("evidence", "evidence.json", aips_evidence_schema),
        (
            "evidence_aggregated",
            "evidence-aggregated.json",
            aips_evidence_audit_v2_schema,
        ),
        ("evidence_ai_context", "evidence-ai-context.json", aips_ai_context_schema),
        ("evidence_audit", "evidence-audit.md", aips_evidence_audit_schema),
    ]

    artifacts = []
    for label, filename, schema_id in artifact_specs:
        path = package_dir / filename
        if path.exists() and path.is_file():
            size = path.stat().st_size
            # Use deterministic content hash (volatiles stripped).
            sha256 = _sha256_of_deterministic_content(path)
            artifacts.append(
                {
                    "label": label,
                    "filename": filename,
                    "schema": schema_id,
                    "size_bytes": size,
                    "sha256": sha256,
                }
            )

    total_size = sum(a["size_bytes"] for a in artifacts)

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "schema_version": MANIFEST_VERSION,
        "analyzer": {
            "name": "aips-analyzer",
            "version": analyzer_version,
        },
        "target_project": {
            "name": project_name,
        },
        "schemas": {
            "evidence": aips_evidence_schema,
            "evidence_aggregated": aips_evidence_audit_v2_schema,
            "evidence_ai_context": aips_ai_context_schema,
            "evidence_audit": aips_evidence_audit_schema,
        },
        "artifacts": artifacts,
        "total_size_bytes": total_size,
        "generated_at": analyzed_at,
        "generation_note": (
            "Deterministic core (artifacts, sizes, sha256) is "
            "stable for the same analyzer version and project "
            "state. sha256 is computed from volatile-stripped "
            "content so that timestamps do not affect hash "
            "stability. The `generated_at` field is non-deterministic "
            "wall-clock metadata and is the only intentionally "
            "volatile field. All artifact paths are relative; this "
            "manifest is portable across machines."
        ),
    }

    out_path = package_dir / "manifest.json"
    out_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _relative_path_for_display(path: Path, base: Path) -> str:
    """Alias for clarity in this module."""
    return _relative_path(path, base)
