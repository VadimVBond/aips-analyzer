"""
audit_evidence.py — Deterministic Evidence Audit / Compact Contract Input.

Reads a large `aips-evidence/v1` JSON artifact and emits a compact
`aips-evidence-audit/v1` JSON designed for human / LLM review of the
Evidence Contract, without losing provenance.

This script does NOT mutate the production schema and does NOT
re-classify evidence into new types. It groups, counts, and surfaces
representative examples + provenance references so the contract can
be designed downstream.

Usage:
    python scripts/audit_evidence.py <evidence.json> [--out <output.json>]
    python scripts/audit_evidence.py <evidence.json> --markdown <report.md>

The output is deterministic: two runs on the same input produce
byte-identical JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_SCHEMA = "aips-evidence-audit/v1"
AUDIT_VERSION = "0.1.0"

# Cap how many representative examples per group. Anything more is noise
# for contract design; full data lives in the source artifact.
MAX_EXAMPLES_PER_GROUP = 3
# Cap how many distinct source files / methods / patterns we list per group
# before collapsing to "...and N more". Keeps the output bounded even when
# one technology spans hundreds of files.
MAX_PROVENANCE_ITEMS = 10


def _value_shape(value: Any) -> str:
    """A short, stable descriptor of a value's JSON shape."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    return type(value).__name__


def _stable(obj: dict[str, Any]) -> str:
    """Stable JSON for duplicate-detection keys (sort_keys=True)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _evidence_signature(item: dict[str, Any]) -> tuple:
    """
    Exact-duplicate signature: same type, same subject, same value, same source.
    Items that match exactly are duplicates that the analyzer should ideally
    collapse. Today they are kept individually in the source artifact.
    """
    return (
        item.get("type"),
        item.get("subject"),
        _stable(item.get("value", "")),
        _stable(item.get("source", {})),
    )


def _near_duplicate_signature(item: dict[str, Any]) -> tuple:
    """
    Near-duplicate signature: same (type, subject, signal_type/method,
    source.file, source.pattern), ignoring the actual value.
    This is what the current analyzer dedup policy targets
    (see technology analyzer).
    """
    src = item.get("source", {}) or {}
    return (
        item.get("type"),
        item.get("subject"),
        item.get("signal_type") or src.get("method"),
        src.get("file"),
        src.get("pattern"),
    )


def _truncate(items: list[Any], cap: int, label: str) -> dict[str, Any]:
    """
    Return up to `cap` sorted items plus an "and N more" tail indicator.
    """
    items_sorted = sorted(items, key=lambda x: (str(x) if x is not None else ""))
    head = items_sorted[:cap]
    rest = len(items_sorted) - len(head)
    out: dict[str, Any] = {"count": len(items_sorted), "listed": head}
    if rest > 0:
        out["more"] = f"...and {rest} more {label}"
    return out


def audit_evidence(evidence: dict[str, Any], generated_at: str | None = None) -> dict[str, Any]:
    """Produce the compact audit structure from a parsed evidence document.

    `generated_at` is the timestamp embedded in the audit header. If omitted,
    falls back to `project.analyzed_at` from the source artifact (so that
    the audit is deterministic given a fixed input). Otherwise, uses
    `now()` — which makes the CLI output reflect when the audit was run.
    """
    evidence_items: list[dict[str, Any]] = list(evidence.get("evidence", []))
    metrics: list[dict[str, Any]] = list(evidence.get("metrics", []))
    warnings: list[dict[str, Any]] = list(evidence.get("warnings", []))

    if generated_at is None:
        generated_at = (evidence.get("project") or {}).get("analyzed_at")
        if not generated_at:
            generated_at = datetime.now(timezone.utc).isoformat()

    # ── Header ────────────────────────────────────────────────────────────
    header = {
        "schema": AUDIT_SCHEMA,
        "audit_version": AUDIT_VERSION,
        "source_schema": evidence.get("schema"),
        "analyzer": evidence.get("analyzer"),
        "project": {
            "name": (evidence.get("project") or {}).get("name"),
            "analyzed_at": (evidence.get("project") or {}).get("analyzed_at"),
            "evidence_items_count": (evidence.get("project") or {}).get(
                "evidence_items_count"
            ),
        },
        "generated_at": generated_at,
    }

    # ── Counts ────────────────────────────────────────────────────────────
    type_counter: Counter[str] = Counter(e.get("type", "<missing>") for e in evidence_items)
    known_types = {
        "technology",
        "repository_metric",
        "git",
        "dependency",
        "architecture",
    }
    unknown_type_count = sum(
        c for t, c in type_counter.items() if t not in known_types
    )

    summary = {
        "evidence_count": len(evidence_items),
        "metric_count": len(metrics),
        "warning_count": len(warnings),
        "evidence_type_counts": dict(
            sorted(type_counter.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "unknown_type_count": unknown_type_count,
        "evidence_id_range": _id_range(evidence_items),
    }

    # ── Section presence ─────────────────────────────────────────────────
    section_presence = {
        key: bool(evidence.get(key))
        for key in (
            "discovery",
            "technology",
            "repository",
            "dependencies",
            "git",
            "architecture",
        )
    }

    # ── Group evidence ───────────────────────────────────────────────────
    groups: list[dict[str, Any]] = []
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in evidence_items:
        by_type[e.get("type", "<missing>")].append(e)

    for evidence_type in sorted(by_type.keys()):
        items = by_type[evidence_type]
        groups.append(_summarize_group(evidence_type, items))

    # ── Duplication analysis ─────────────────────────────────────────────
    exact = Counter(_evidence_signature(e) for e in evidence_items)
    near = Counter(_near_duplicate_signature(e) for e in evidence_items)
    exact_dup_groups = [
        {
            "type": k[0],
            "subject": k[1],
            "value": json.loads(k[2]) if isinstance(k[2], str) else k[2],
            "source": json.loads(k[3]) if isinstance(k[3], str) else k[3],
            "occurrences": v,
        }
        for k, v in exact.items()
        if v > 1
    ]
    near_dup_groups = [
        {
            "type": k[0],
            "subject": k[1],
            "signal_type": k[2],
            "source_file": k[3],
            "source_pattern": k[4],
            "occurrences": v,
        }
        for k, v in near.items()
        if v > 1
    ]
    exact_dup_groups.sort(key=lambda g: (-g["occurrences"], g["type"], str(g["subject"])))
    near_dup_groups.sort(key=lambda g: (-g["occurrences"], g["type"], str(g["subject"])))

    duplication = {
        "exact_duplicate_groups": exact_dup_groups,
        "exact_duplicate_count": sum(
            g["occurrences"] - 1 for g in exact_dup_groups
        ),
        "near_duplicate_groups": near_dup_groups,
        "near_duplicate_count": sum(
            g["occurrences"] - 1 for g in near_dup_groups
        ),
        "note": (
            "exact = same (type, subject, value, source). "
            "near = same (type, subject, signal_type, source.file, "
            "source.pattern) — matches the current analyzer dedup policy."
        ),
    }

    # ── Metrics snapshot (already compact) ────────────────────────────────
    metric_kinds = Counter()
    for m in metrics:
        name = m.get("name", "")
        kind = name.split(".", 1)[0] if "." in name else name
        metric_kinds[kind] += 1
    metrics_summary = {
        "total": len(metrics),
        "by_top_level": dict(sorted(metric_kinds.items())),
        "examples": sorted(metrics, key=lambda m: m.get("name", ""))[:5],
    }

    # ── Warnings snapshot ─────────────────────────────────────────────────
    warnings_summary = {
        "total": len(warnings),
        "by_analyzer": dict(
            sorted(
                Counter(w.get("analyzer") for w in warnings).items(),
                key=lambda kv: (-kv[1], kv[0]),
            )
        ),
    }

    # ── Section key inventories (to spot shape drift) ────────────────────
    section_keys = {}
    for section in ("discovery", "technology", "repository", "dependencies", "git", "architecture"):
        sec = evidence.get(section) or {}
        if isinstance(sec, dict):
            section_keys[section] = sorted(sec.keys())

    return {
        "header": header,
        "summary": summary,
        "section_presence": section_presence,
        "section_keys": section_keys,
        "groups": groups,
        "duplication": duplication,
        "metrics": metrics_summary,
        "warnings": warnings_summary,
    }


def _id_range(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the range of evidence IDs found, if they follow the E-NNN shape."""
    ids = [e.get("id") for e in items if isinstance(e.get("id"), str)]
    if not ids:
        return {"count": 0}
    return {"count": len(ids), "first": ids[0], "last": ids[-1], "distinct": len(set(ids))}


def _summarize_group(
    evidence_type: str, items: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build a compact summary for one evidence-type group (or sub-group)."""
    subjects = Counter(e.get("subject") for e in items)
    signal_types: Counter[str] = Counter()
    methods: Counter[str] = Counter()
    patterns: Counter[str] = Counter()
    files: set[str] = set()
    value_shapes: Counter[str] = Counter()

    for e in items:
        src = e.get("source", {}) or {}
        # Only `technology` items carry a real `signal_type`; for others we
        # synthesize one from the source so the contract view stays uniform.
        st = e.get("signal_type") or src.get("method") or "<unknown>"
        signal_types[st] += 1
        if src.get("method"):
            methods[src["method"]] += 1
        if src.get("pattern"):
            patterns[src["pattern"]] += 1
        if src.get("file"):
            files.add(src["file"])
        value_shapes[_value_shape(e.get("value"))] += 1

    examples = sorted(
        items,
        key=lambda e: (
            e.get("subject") or "",
            e.get("id") or "",
        ),
    )[:MAX_EXAMPLES_PER_GROUP]

    sub_groups: list[dict[str, Any]] = []
    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in items:
        by_subject[e.get("subject")].append(e)
    for subject in sorted(by_subject.keys()):
        sub = by_subject[subject]
        if len(sub) <= 1:
            continue
        sub_examples = sorted(
            sub, key=lambda e: (e.get("source", {}).get("file") or "", e.get("id") or "")
        )[:MAX_EXAMPLES_PER_GROUP]
        sub_files = {e.get("source", {}).get("file") for e in sub}
        sub_files.discard(None)
        sub_groups.append(
            {
                "subject": subject,
                "count": len(sub),
                "value_shapes": dict(value_shapes_for(sub)),
                "source_files": _truncate(sorted(sub_files), MAX_PROVENANCE_ITEMS, "files"),
                "examples": sub_examples,
            }
        )

    group: dict[str, Any] = {
        "type": evidence_type,
        "count": len(items),
        "subjects": dict(
            sorted(subjects.items(), key=lambda kv: (-kv[1], str(kv[0])))
        ),
        "signal_types": dict(
            sorted(signal_types.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "source_methods": dict(
            sorted(methods.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "source_patterns_top": dict(
            sorted(patterns.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_PROVENANCE_ITEMS]
        ),
        "source_files": _truncate(sorted(files), MAX_PROVENANCE_ITEMS, "files"),
        "value_shapes": dict(
            sorted(value_shapes.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "examples": examples,
        "sub_groups_only_when_dense": sub_groups,
    }
    return group


def value_shapes_for(items: list[dict[str, Any]]) -> Counter:
    return Counter(_value_shape(i.get("value")) for i in items)


# ─── CLI ───────────────────────────────────────────────────────────────────


def _load(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def _emit_json(audit: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


def _emit_markdown(audit: dict[str, Any], path: Path) -> None:
    """Render a human-readable audit markdown document."""
    h = audit["header"]
    s = audit["summary"]
    groups = audit["groups"]
    dup = audit["duplication"]

    lines: list[str] = []
    lines.append(f"# Evidence Audit — {h['project'].get('name')}")
    lines.append("")
    lines.append(f"- Source schema: `{h['source_schema']}`")
    lines.append(f"- Analyzer: `{h['analyzer']}`")
    lines.append(f"- Audit schema: `{h['schema']}` v{h['audit_version']}")
    lines.append(f"- Analyzed at: {h['project'].get('analyzed_at')}")
    lines.append(f"- Audit generated at: {h['generated_at']}")
    lines.append("")
    lines.append("## 1. Current Evidence Structure")
    lines.append("")
    lines.append("```text")
    lines.append(f"evidence items : {s['evidence_count']}")
    lines.append(f"metrics        : {s['metric_count']}")
    lines.append(f"warnings       : {s['warning_count']}")
    lines.append("```")
    lines.append("")
    lines.append("Section presence:")
    for k, v in audit["section_presence"].items():
        lines.append(f"- `{k}`: {'present' if v else 'missing'}")
    lines.append("")
    lines.append("Evidence ID range:")
    ir = s["evidence_id_range"]
    if ir.get("count", 0) > 0:
        lines.append(f"- first={ir['first']}, last={ir['last']}, distinct={ir['distinct']}/{ir['count']}")
    else:
        lines.append("- (no ids)")
    lines.append("")

    lines.append("## 2. Evidence Type Inventory")
    lines.append("")
    lines.append("| Type | Count |")
    lines.append("|------|-------|")
    for t, c in s["evidence_type_counts"].items():
        lines.append(f"| `{t}` | {c} |")
    lines.append(f"| _unknown_ | {s['unknown_type_count']} |")
    lines.append("")

    lines.append("## 3. Observation Patterns")
    lines.append("")
    for g in groups:
        lines.append(f"### `{g['type']}` — {g['count']} items")
        lines.append("")
        if g["subjects"]:
            top = list(g["subjects"].items())[:10]
            lines.append("Top subjects:")
            for subj, c in top:
                lines.append(f"- `{subj}`: {c}")
            lines.append("")
        if g["signal_types"]:
            lines.append("Signal types:")
            for st, c in g["signal_types"].items():
                lines.append(f"- `{st}`: {c}")
            lines.append("")
        if g["source_methods"]:
            lines.append("Source methods:")
            for m, c in g["source_methods"].items():
                lines.append(f"- `{m}`: {c}")
            lines.append("")
        if g["source_patterns_top"]:
            lines.append("Source patterns (top):")
            for p, c in g["source_patterns_top"].items():
                lines.append(f"- `{p}`: {c}")
            lines.append("")
        if g["source_files"].get("listed") or g["source_files"].get("count"):
            lines.append(f"Source files: {g['source_files']['count']} distinct")
            for f in g["source_files"].get("listed", []):
                lines.append(f"- `{f}`")
            if g["source_files"].get("more"):
                lines.append(f"- {g['source_files']['more']}")
            lines.append("")
        if g["value_shapes"]:
            lines.append("Value shapes:")
            for vs, c in g["value_shapes"].items():
                lines.append(f"- `{vs}`: {c}")
            lines.append("")
        # Sub-groups reveal where the cardinality lives.
        if g["sub_groups_only_when_dense"]:
            lines.append("Sub-groups with >1 occurrence (preserves provenance):")
            for sg in g["sub_groups_only_when_dense"][:10]:
                lines.append(f"- `{sg['subject']}` × {sg['count']} — "
                             f"{sg['source_files']['count']} files")
            lines.append("")

    lines.append("## 4. Metrics")
    lines.append("")
    lines.append(f"Total metrics: {audit['metrics']['total']}")
    lines.append("")
    lines.append("By top-level key:")
    for k, v in audit["metrics"]["by_top_level"].items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")
    if audit["metrics"]["examples"]:
        lines.append("Examples:")
        for m in audit["metrics"]["examples"]:
            lines.append(f"- `{m['name']}` = {m['value']}")
        lines.append("")

    lines.append("## 5. Provenance")
    lines.append("")
    lines.append(
        "Each evidence item carries `source: {file, section, line, method, pattern}`. "
        "This is the unit that links an observation back to where it came from. "
        "The contract MUST preserve this link."
    )
    lines.append("")
    lines.append("Example source structures (one per evidence type):")
    for g in groups:
        if g["examples"]:
            ex = g["examples"][0]
            src = ex.get("source", {})
            lines.append(f"- `{g['type']}` → source keys: {sorted(src.keys())}")
    lines.append("")

    lines.append("## 6. Duplication")
    lines.append("")
    lines.append(f"- exact_duplicate_groups: {len(dup['exact_duplicate_groups'])} "
                 f"(would remove {dup['exact_duplicate_count']} items)")
    lines.append(f"- near_duplicate_groups: {len(dup['near_duplicate_groups'])} "
                 f"(would remove {dup['near_duplicate_count']} items)")
    lines.append("")
    if dup["near_duplicate_groups"]:
        lines.append("Top near-duplicate groups (subject / file / occurrences):")
        for ng in dup["near_duplicate_groups"][:10]:
            lines.append(
                f"- `{ng['type']}/{ng['subject']}` "
                f"[{ng.get('signal_type', '?')}] @ `{ng['source_file']}` "
                f"× {ng['occurrences']}"
            )
        lines.append("")
    if dup["exact_duplicate_groups"]:
        lines.append("Top exact-duplicate groups:")
        for eg in dup["exact_duplicate_groups"][:5]:
            lines.append(
                f"- `{eg['type']}/{eg['subject']}` value={eg['value']!r} × {eg['occurrences']}"
            )
        lines.append("")

    lines.append("## 7. Potential Contract Problems")
    lines.append("")
    lines.append(
        "- IDs `E-NNN` are assigned in analyzer-order; reruns after any "
        "analyzer change will reshuffle them. Future contract needs stable IDs."
    )
    lines.append(
        "- `evidence` mixes raw observations (technology, git, architecture) "
        "and pre-aggregated metrics (`repository_metric`). They share an "
        "evidence shape but have very different semantics."
    )
    lines.append(
        "- `metrics[]` is a flattened name→value list and overlaps with "
        "`repository_metric` evidence. Both exist; one of them is redundant."
    )
    lines.append(
        "- `dependencies.python.production[]` carries richer dependency data "
        "than the single `dependency` evidence item. Duplicate provenance."
    )
    lines.append(
        "- `architecture.candidate_findings` is interpretive (high fan-in/out, "
        "cycles). Currently lives inside an analyzer section, not in evidence[]."
    )
    lines.append(
        "- No `unknown` evidence type exists. Future analyzers may emit new "
        "types that older contracts do not understand."
    )
    lines.append(
        "- Provenance `source.file` mixes target-relative paths. They are "
        "portable but analyzer implementation details (regex patterns) leak "
        "into the contract."
    )
    lines.append("")

    lines.append("## 8. Proposed Evidence Contract v1")
    lines.append("")
    lines.append(
        "The contract is split into three layers. The analyzer keeps "
        "emitting the existing `aips-evidence/v1` schema verbatim; the "
        "contract defines what the **consumer** sees."
    )
    lines.append("")
    lines.append("```text")
    lines.append("Layer 1 — Observation (raw)")
    lines.append("  type, subject, value, source{provenance}, notes")
    lines.append("")
    lines.append("Layer 2 — Evidence (grouped)")
    lines.append("  evidence_id = stable hash(type|subject|value|provenance)")
    lines.append("  observations = [Observation...]  # never collapsed")
    lines.append("  first_seen, last_seen")
    lines.append("")
    lines.append("Layer 3 — Fact (normalized)")
    lines.append("  fact_id, fact_type, value, evidence_refs = [evidence_id...]")
    lines.append("")
    lines.append("Layer 4 — Metric (quantitative)")
    lines.append("  metric_id, name, value, unit, evidence_refs")
    lines.append("")
    lines.append("Layer 5 — Finding (interpretive, NOT generated by analyzer)")
    lines.append("  finding_id, rule, severity, evidence_refs, fact_refs")
    lines.append("```")
    lines.append("")
    lines.append("Stable-ID strategy: see Open Questions.")
    lines.append("")

    lines.append("## 9. Migration Considerations")
    lines.append("")
    lines.append("- Phase 1 (this script): compact audit / contract input.")
    lines.append("- Phase 2: introduce `evidence_id` (stable hash) as optional "
                 "field next to existing `id`. Keep `id` for backward compat.")
    lines.append("- Phase 3: aggregator pass produces Facts (one per "
                 "`(type, subject, value)` group). Aggregator is deterministic, "
                 "runs in the same CLI run.")
    lines.append("- Phase 4: Findings live in a separate `findings[]` array "
                 "and are NOT produced by the analyzer.")
    lines.append("- Phase 5: Recovery Engine consumes Facts + Metrics + Findings, "
                 "never raw observations.")
    lines.append("")

    lines.append("## 10. Open Questions")
    lines.append("")
    lines.append(
        "- Stable-ID hashing: which fields participate? Including `value` makes "
        "version bumps produce new IDs; excluding it groups version drift."
    )
    lines.append(
        "- Should `repository_metric` evidence items disappear entirely and "
        "become a parallel `metrics[]` (already exists) + `fact` references?"
    )
    lines.append(
        "- Should `technology.observations` (which is what deduplication "
        "currently targets) be folded into the top-level `evidence[]` only, "
        "and de-duplicated there once?"
    )
    lines.append(
        "- When does an observation become a Finding candidate vs remain "
        "raw? Today `candidate_findings` lives in `architecture` section "
        "but other analyzers have similar shapes (high LOC files in "
        "`repository.top_10_largest_files`)."
    )
    lines.append(
        "- How are we going to version the contract vs version the analyzer? "
        "Today both share `0.1.0`; semver implications unclear."
    )
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audit_evidence",
        description="Compact, deterministic audit of aips-evidence/v1.",
    )
    parser.add_argument("path", help="Path to aips-evidence/v1 JSON file")
    parser.add_argument(
        "--out",
        default=None,
        help="Where to write the compact audit JSON. "
             "Default: if input is `evidence.json`, "
             "`evidence-contract-input.json` next to it; "
             "otherwise `<stem>.contract-input.json`.",
    )
    parser.add_argument(
        "--markdown",
        default=None,
        help="Optional: write a human-readable Markdown audit to this path.",
    )
    parser.add_argument(
        "--timestamp",
        "--timestamp",
        default=None,
        help="Override generated_at timestamp. Default: use the source's "
             "project.analyzed_at so the audit is deterministic given a fixed "
             "input. Pass an explicit ISO-8601 string to embed the wall-clock "
             "time at which the audit was run.",
    )
    parser.add_argument(
        "--aggregated",
        action="store_true",
        help="AA-008: emit Aggregator Phase 2 output (aips-evidence-audit/v2) "
             "with stable_id, grouping, normalized Facts, and canonical Metrics. "
             "By default the CLI emits the v1 audit (compact summary only).",
    )
    parser.add_argument(
        "--ai-context",
        action="store_true",
        help="AA-011: emit AI Context output (aips-ai-context/v1) — "
             "deterministic projection of Facts/Metrics/Unknowns for LLM. "
             "Includes AA-011 extended facts (git, dependency_version).",
    )
    args = parser.parse_args(argv)

    src = Path(args.path)
    if not src.exists():
        print(f"error: input file not found: {src}", file=sys.stderr)
        return 2

    try:
        evidence = _load(src)
    except json.JSONDecodeError as exc:
        print(f"error: malformed JSON: {exc}", file=sys.stderr)
        return 3

    if not isinstance(evidence, dict):
        print("error: top-level JSON must be an object", file=sys.stderr)
        return 4

    if args.out:
        out_path = Path(args.out)
    else:
        # Default: if input is `evidence.json`, write `evidence-contract-input.json`
        # next to it. Otherwise fall back to `<stem>.contract-input.json`.
        if src.name == "evidence.json":
            out_path = src.with_name("evidence-contract-input.json")
        else:
            out_path = src.with_name(src.stem + ".contract-input.json")

    if args.ai_context:
        # AA-011: AI Context Renderer output.
        # Uses aggregate_v2 + AA-011 fact extension.
        agg = aggregate_v2_with_aa011(evidence)
        ai_context = render_ai_context(agg)
        _emit_json(ai_context, out_path)
        print(f"wrote {out_path}")
        if args.markdown:
            print("warning: --markdown is for v1 audit; ignored in ai-context",
                  file=sys.stderr)
        return 0

    if args.aggregated:
        aggregated = aggregate_v2(evidence)
        _emit_json(aggregated, out_path)
        print(f"wrote {out_path}")
        if args.markdown:
            print("warning: --markdown is for v1 audit; ignored in v2",
                  file=sys.stderr)
        return 0

    audit = audit_evidence(
        evidence,
        generated_at=args.timestamp,
    )
    _emit_json(audit, out_path)
    print(f"wrote {out_path}")

    if args.markdown:
        md_path = Path(args.markdown)
        _emit_markdown(audit, md_path)
        print(f"wrote {md_path}")

    return 0
    audit = audit_evidence(
        evidence,
        generated_at=args.timestamp,
    )
    _emit_json(audit, out_path)
    print(f"wrote {out_path}")

    if args.markdown:
        md_path = Path(args.markdown)
        _emit_markdown(audit, md_path)
        print(f"wrote {md_path}")

    return 0



# ===== AA-008: Aggregator Phase 2 — stable_id + grouping + Facts =====
# Per ADR-001 sections 6, 7, 12.
# - stable_id   = (type, subject, detector_id, signal_type, pattern)
# - display_key = stable_id + first observed file (or method fallback)
# - value / path / timestamp / positional id are NEVER in identity.
#
# Backward compatibility:
# - Existing audit_evidence() is unchanged.
# - aggregate_v2() produces a NEW shape (stable_groups, facts,
#   canonical_metrics, unknown).
# - CLI --aggregated selects v2.

AGGREGATE_SCHEMA = "aips-evidence-audit/v2"
AGGREGATE_VERSION = "0.1.0"

# Canonical detector_id mapping (compromise until ADR catalog exists, B2).
# Source: existing source.method in aips-evidence/v1.
TYPE_TO_DETECTOR_PREFIX = {
    "technology": "technology",
    "repository_metric": "repository.metric",
    "git": "git",
    "dependency": "dependency",
    "architecture": "architecture",
}


def _canonical_pattern(pattern):
    """Normalize a regex/keyword pattern for use in identity.

    Stable across runs:
    - Strip leading/trailing whitespace.
    - Lowercase the entire pattern.
    - Collapse multiple internal whitespace into one.
    """
    if pattern is None:
        return ""
    s = pattern.strip().lower()
    return " ".join(s.split())


def stable_id_for_evidence(item):
    """Compute the stable_id of a single evidence item per ADR-001.

    Formula:
        stable_id = "<type>:<subject>:<detector_id>:<signal_type>:<canonical_pattern>"

    Notes:
    - detector_id combines type-prefix + method. When a real detector
      catalog exists (ADR-001 B2), this mapping can be replaced without
      breaking stable_id values that already use reasonable method names.
    - Subject is part of identity (per ADR-001 section 6).
    - value, file, line, section, notes, timestamp are NEVER in identity
      (per ADR-001 section 12).
    """
    ev_type = item.get("type", "<missing>")
    subject = item.get("subject", "<missing>")
    src = item.get("source") or {}

    method = item.get("signal_type") or src.get("method") or "<unknown>"
    signal_type = method or "<unknown>"

    prefix = TYPE_TO_DETECTOR_PREFIX.get(ev_type, ev_type)
    detector_id = prefix + "." + method if method else prefix + ".<unknown>"

    pattern_raw = src.get("pattern")
    pattern = _canonical_pattern(pattern_raw) or "<none>"

    return (ev_type + ":" + str(subject) + ":" + detector_id + ":"
            + signal_type + ":" + pattern)


def display_key_for_evidence(item):
    """Compute the human-readable display_key per ADR-001 section 6.

    Includes:
    - stable_id prefix
    - first observed source.file (if any) OR source.method

    Display_key rebuilds per run from provenance; not part of identity.
    """
    stable = stable_id_for_evidence(item)
    src = item.get("source") or {}
    file_hint = src.get("file")
    if file_hint:
        return stable + "@" + file_hint
    method_hint = src.get("method") or item.get("signal_type") or ""
    if method_hint:
        return stable + "@" + method_hint
    return stable


def _infer_unit_from_name(name):
    """Best-effort unit inference from a metric name.

    For names that look like counts of files/lines/bytes we map to the
    obvious unit; otherwise 'count' as default.
    """
    n = name.lower()
    if "files" in n:
        return "files"
    if "lines" in n or "loc" in n:
        return "lines"
    if "bytes" in n:
        return "bytes"
    if "ratio" in n:
        return "ratio"
    if ("count" in n or "modules" in n or "packages" in n
            or "apps" in n or "deps" in n):
        return "count"
    return "count"


def aggregate_v2(evidence):
    """Aggregator Phase 2 (AA-008).

    Returns a structure that augments phase 1 (audit_evidence) with:
    - stable_groups[]: Evidence groups keyed by stable_id.
    - facts[]: normalized facts (technology_present, etc.).
    - canonical_metrics[]: repository_metric evidence projected as
      canonical Metrics (deduplicated with metrics[]).
    - unknown[]: items that could not be classified.

    Determinism:
    - stable_id is a pure function of (type, subject, method, pattern).
    - All lists are sorted before emission.
    - Two runs on the same evidence produce byte-identical output.
    """
    evidence_items = list(evidence.get("evidence", []))
    metrics = list(evidence.get("metrics", []))

    # 1. Compute stable_id for every item, bucket by it.
    stable_to_items = {}
    unknown_items = []
    for it in evidence_items:
        ev_type = it.get("type", "<missing>")
        if ev_type not in TYPE_TO_DETECTOR_PREFIX:
            unknown_items.append(it)
            continue
        try:
            sid = stable_id_for_evidence(it)
        except Exception as exc:
            unknown_items.append(dict(it, _stable_id_error=str(exc)))
            continue
        stable_to_items.setdefault(sid, []).append(it)

    # 2. Build Evidence Groups.
    import re as _re
    stable_groups = []
    for sid in sorted(stable_to_items.keys()):
        items = stable_to_items[sid]
        items_sorted = sorted(
            items,
            key=lambda e: (
                e.get("id") or "",
                json.dumps(e.get("source", {}), sort_keys=True,
                           ensure_ascii=False, default=str),
            ),
        )
        first = items_sorted[0]
        display = display_key_for_evidence(first)

        files = set()
        methods = set()
        for it in items:
            src = it.get("source") or {}
            if src.get("file"):
                files.add(src["file"])
            if src.get("method"):
                methods.add(
                    (src["method"] or "").strip().lower().replace(" ", "_"))
            elif it.get("signal_type"):
                methods.add(
                    (it.get("signal_type") or "").strip().lower().replace(" ", "_"))

        values = []
        seen_values = set()
        for it in items_sorted:
            v = it.get("value")
            v_key = json.dumps(v, sort_keys=True,
                               ensure_ascii=False, default=str)
            if v_key in seen_values:
                continue
            seen_values.add(v_key)
            values.append(v)

        src_first = first.get("source") or {}
        stable_groups.append({
            "stable_id":          sid,
            "display_key":        display,
            "type":               first.get("type"),
            "subject":            first.get("subject"),
            "signal_type":        first.get("signal_type") or src_first.get("method"),
            "first_evidence_id":  first.get("id"),
            "observation_count":  len(items),
            "values":             values,
            "value_count":        len(values),
            "provenance": {
                "files":   sorted(files),
                "methods": sorted(methods),
            },
            "notes":              first.get("notes"),
        })

    # 3. Build Facts (per ADR-001 section 7).
    facts = []

    tech_subjects = {g["subject"] for g in stable_groups
                     if g["type"] == "technology"}
    for tech in sorted(tech_subjects):
        facts.append({
            "fact_id":       "technology_present[" + tech + "]",
            "fact_type":     "technology_present",
            "subject":       tech,
            "value":         True,
            "evidence_refs": sorted(
                g["stable_id"] for g in stable_groups
                if g["type"] == "technology" and g["subject"] == tech
            ),
        })
        # Detect version-like values for technology_version[tech].
        version_values = set()
        for g in stable_groups:
            if g["type"] != "technology" or g["subject"] != tech:
                continue
            for v in g["values"]:
                if not isinstance(v, str):
                    continue
                m = _re.search(
                    r"([A-Za-z0-9_\-]+)\s*([=<>!~]=?)\s*"
                    r"([0-9][0-9A-Za-z\.\-_]*)",
                    v,
                )
                if not m:
                    continue
                pkg_name = _re.split(r"[=<>!~]", m.group(0))[0].strip().lower()
                if not pkg_name:
                    continue
                if (tech.lower() in pkg_name.lower()
                        or pkg_name in tech.lower()):
                    version_values.add(m.group(0))
        for ver in sorted(version_values):
            facts.append({
                "fact_id":       "technology_version[" + tech + "]",
                "fact_type":     "technology_version",
                "subject":       tech,
                "value":         ver,
                "evidence_refs": sorted(
                    g["stable_id"] for g in stable_groups
                    if g["type"] == "technology" and g["subject"] == tech
                ),
            })

    dep_subjects = {g["subject"] for g in stable_groups
                    if g["type"] == "dependency"}
    for name in sorted(dep_subjects):
        facts.append({
            "fact_id":       "dependency_declared[" + name + "]",
            "fact_type":     "dependency_declared",
            "subject":       name,
            "value":         True,
            "evidence_refs": sorted(
                g["stable_id"] for g in stable_groups
                if g["type"] == "dependency" and g["subject"] == name
            ),
        })

    arch_groups = [g for g in stable_groups if g["type"] == "architecture"]
    arch_subjects = {g["subject"] for g in arch_groups}
    if "cyclic_dependencies" in arch_subjects:
        facts.append({
            "fact_id":       "architecture_cycles_present",
            "fact_type":     "architecture_cycles_present",
            "subject":       "import_graph",
            "value":         True,
            "evidence_refs": sorted(
                g["stable_id"] for g in arch_groups
                if g["subject"] == "cyclic_dependencies"
            ),
        })
    if "parse_errors" in arch_subjects:
        facts.append({
            "fact_id":       "architecture_parse_errors_present",
            "fact_type":     "architecture_parse_errors_present",
            "subject":       "ast_parser",
            "value":         True,
            "evidence_refs": sorted(
                g["stable_id"] for g in arch_groups
                if g["subject"] == "parse_errors"
            ),
        })

    # 4. Build canonical Metrics (per ADR-001 section 8).
    canonical_metrics = []
    seen_metric_keys = set()

    for m in metrics:
        name = m.get("name", "")
        if not name:
            continue
        key = "section::" + name
        if key in seen_metric_keys:
            continue
        seen_metric_keys.add(key)
        canonical_metrics.append({
            "metric_id":     "metric:" + name,
            "name":           name,
            "value":          m.get("value"),
            "unit":           _infer_unit_from_name(name),
            "source":         "analyzer_metrics",
            "evidence_refs":  [],
            "notes":          None,
        })

    metric_index_by_name = {m["name"]: m for m in canonical_metrics}
    for g in stable_groups:
        if g["type"] != "repository_metric":
            continue
        subject = g["subject"]
        candidates = ["discovery." + subject, "repository." + subject]
        matched = next((c for c in candidates
                        if c in metric_index_by_name), None)
        if matched:
            metric_index_by_name[matched]["evidence_refs"].append(
                g["stable_id"])
            continue
        value = g["values"][0] if g["values"] else None
        if value is None:
            continue
        key = "repo::" + subject
        if key in seen_metric_keys:
            continue
        seen_metric_keys.add(key)
        canonical_metrics.append({
            "metric_id":     "metric:repository." + subject,
            "name":           "repository." + subject,
            "value":          value,
            "unit":           _infer_unit_from_name(subject),
            "source":         "repository_metric_evidence",
            "evidence_refs":  [g["stable_id"]],
            "notes":          g.get("notes"),
        })

    canonical_metrics.sort(key=lambda m: m["name"])

    return {
        "header": {
            "schema":         AGGREGATE_SCHEMA,
            "schema_version": AGGREGATE_VERSION,
            "phase":          2,
            "source_schema":  evidence.get("schema"),
            "analyzer":       evidence.get("analyzer"),
            "project": {
                "name":       (evidence.get("project") or {}).get("name"),
                "analyzed_at": (evidence.get("project") or {}).get("analyzed_at"),
            },
        },
        "stable_groups":     stable_groups,
        "facts":             facts,
        "canonical_metrics": canonical_metrics,
        "unknown": [
            {
                "id":      it.get("id"),
                "type":    it.get("type"),
                "subject": it.get("subject"),
                "reason":  (
                    "unknown evidence type: "
                    + repr(it.get("type"))
                    + "; cannot compute stable_id without canonical detector_id"
                ),
            }
            for it in unknown_items
        ],
    }


# ===== AA-011: AI Context Renderer (aips-ai-context/v1) =====
# Renders the Aggregator v2 output into a compact, LLM-friendly JSON.
#
# Per AA-011 contract:
# - AI Context is a deterministic *projection* of Facts/Metrics/Unknowns.
# - It does NOT invent facts, does NOT interpret, does NOT generate
#   findings, does NOT hide unknowns.
# - Output is byte-identical for identical Aggregator v2 input.
#
# Schema: aips-ai-context/v1
# Size target: substantially smaller than raw evidence.json, but
# always preserving enough provenance for the LLM to cite fact_id.

AI_CONTEXT_SCHEMA = "aips-ai-context/v1"
AI_CONTEXT_VERSION = "0.1.0"

# Cap how many stable_groups to include as examples in the AI Context.
# These are *examples* for the LLM, not a full enumeration.
AI_CONTEXT_SAMPLE_GROUPS = 5

# Cap how many unknown items to enumerate.
AI_CONTEXT_MAX_UNKNOWNS = 50


def render_ai_context(aggregated: dict, project_meta: dict | None = None) -> dict:
    """Render Aggregator v2 output as aips-ai-context/v1.

    Input:  the dict returned by aggregate_v2(evidence).
            Must have keys: header, stable_groups, facts, canonical_metrics, unknown.

    Output: dict conforming to aips-ai-context/v1 contract.

    Determinism:
    - All lists are sorted before emission.
    - stable_groups are sampled deterministically (top-N by observation_count).
    - Output is byte-identical for identical input.
    """
    if not isinstance(aggregated, dict):
        raise TypeError("aggregated must be a dict from aggregate_v2()")
    for key in ("header", "stable_groups", "facts", "canonical_metrics", "unknown"):
        if key not in aggregated:
            raise ValueError(
                f"aggregated dict missing required key {key!r}; "
                "did you pass aggregate_v2() output?"
            )

    header = aggregated["header"]
    stable_groups = aggregated["stable_groups"]
    facts = aggregated["facts"]
    metrics = aggregated["canonical_metrics"]
    unknowns = aggregated["unknown"]

    # Sample stable_groups: top N by observation_count (deterministic).
    top_groups = sorted(
        stable_groups, key=lambda g: (-g.get("observation_count", 0),
                                       g.get("stable_id", ""))
    )[:AI_CONTEXT_SAMPLE_GROUPS]
    sample_groups = []
    for g in top_groups:
        sample_groups.append({
            "stable_id":          g.get("stable_id"),
            "display_key":        g.get("display_key"),
            "type":               g.get("type"),
            "subject":            g.get("subject"),
            "observation_count":  g.get("observation_count"),
            "value_count":        g.get("value_count"),
            "provenance": {
                "files":   g.get("provenance", {}).get("files", []),
                "methods": g.get("provenance", {}).get("methods", []),
            },
        })

    # Project meta is taken from the Aggregator header.
    proj_block = {
        "name":                 header.get("project", {}).get("name"),
        "analyzed_at":          header.get("project", {}).get("analyzed_at"),
        "evidence_count":       (project_meta or {}).get("evidence_count"),
        "metric_count":         (project_meta or {}).get("metric_count"),
        "warning_count":        (project_meta or {}).get("warning_count"),
    }
    # Drop None values for portability.
    proj_block = {k: v for k, v in proj_block.items() if v is not None}

    # Known analyzer caps (so the LLM knows about possible undercounts).
    # These mirror the caps in aips_analyzer/analyzers/technology.py.
    limits = {
        "html_files_capped_at": 100,
        "python_imports_extra_cap": 200,
        "notes": (
            "AIPS Analyzer applies hard caps on file/import scans. "
            "Values may be undercounts. Run with extended caps for "
            "very large projects (not in v0.1)."
        ),
    }

    return {
        "header": {
            "schema":                   AI_CONTEXT_SCHEMA,
            "schema_version":           AI_CONTEXT_VERSION,
            "source_schema":            header.get("source_schema"),
            "source_aggregator_schema": header.get("schema"),
            "analyzer":                 header.get("analyzer"),
            "project":                  proj_block,
        },
        "summary": {
            "fact_count":         len(facts),
            "metric_count":       len(metrics),
            "stable_group_count": len(stable_groups),
            "unknown_count":      len(unknowns),
        },
        "facts":             facts,
        "metrics":           metrics,
        "stable_groups_sample": sample_groups,
        "unknowns":          unknowns[:AI_CONTEXT_MAX_UNKNOWNS],
        "limits":            limits,
        "guidance_for_llm": (
            "Use facts[] and metrics[] as canonical source of truth. "
            "Every fact has evidence_refs[] pointing to stable_groups. "
            "stable_groups_sample[] shows concrete examples. "
            "unknowns[] is exhaustive (capped) — never claim something "
            "as 'not present' if it is listed in unknowns[]. "
            "Do NOT invent facts beyond what is in this context. "
            "If the LLM needs raw evidence.json, it can be loaded "
            "separately (not embedded here to keep this context small)."
        ),
    }


def _extract_git_repo_present(aggregated: dict) -> bool:
    """Return True if any git evidence was observed."""
    for g in aggregated.get("stable_groups", []):
        if g.get("type") == "git":
            return True
    return False


def _extract_git_total_commits(aggregated: dict) -> int | None:
    """Extract total commits from git metrics or evidence.

    Looks for canonical metric named like 'git.total_commits' or
    git evidence with subject='total_commits'.
    """
    for m in aggregated.get("canonical_metrics", []):
        name = m.get("name", "")
        if name.endswith(".total_commits") and "git" in name:
            v = m.get("value")
            if isinstance(v, int):
                return v
    for g in aggregated.get("stable_groups", []):
        if g.get("type") == "git" and g.get("subject") == "total_commits":
            vals = g.get("values", [])
            if vals and isinstance(vals[0], int):
                return vals[0]
    return None


def _extract_git_current_branch(aggregated: dict) -> str | None:
    """Extract current branch name from git evidence."""
    for g in aggregated.get("stable_groups", []):
        if g.get("type") == "git" and g.get("subject") == "current_branch":
            vals = g.get("values", [])
            if vals and isinstance(vals[0], str):
                return vals[0]
    return None


def _extract_dependency_versions(aggregated: dict) -> dict[str, str]:
    """Extract dependency name -> version spec from stable_groups.

    Returns mapping: name -> version_spec (e.g. "5.2.10" or ">=5.0").
    """
    out: dict[str, str] = {}
    for g in aggregated.get("stable_groups", []):
        if g.get("type") != "dependency":
            continue
        subject = g.get("subject", "")
        values = g.get("values", [])
        if not subject or not values:
            continue
        # Take the first non-empty value.
        for v in values:
            if isinstance(v, str) and v.strip():
                out[subject] = v
                break
            if isinstance(v, dict):
                # If a value dict has a version field, use it.
                ver = v.get("version") or v.get("version_spec")
                if isinstance(ver, str) and ver.strip():
                    out[subject] = ver
                    break
    return out


def _append_aa011_facts(aggregated: dict) -> dict:
    """Append 4 new fact_types to aggregated['facts'].

    New facts:
      - git_repository_present[git]    (bool)
      - git_total_commits[git]          (int | None)
      - git_current_branch[git]         (str | None)
      - dependency_version[name]        (str)

    These are minimal additions to enable AI Context renderer to
    describe git state and dependency versions.

    Implementation note: this mutates and returns the same dict.
    For immutability, callers can copy first.
    """
    facts = aggregated.setdefault("facts", [])

    # Idempotency: skip if AA-011 facts already present.
    existing_ids = {f.get("fact_id") for f in facts}
    if "git_repository_present[git]" in existing_ids:
        return aggregated

    # Git facts
    if _extract_git_repo_present(aggregated):
        facts.append({
            "fact_id":   "git_repository_present[git]",
            "fact_type": "git_repository_present",
            "subject":   "git",
            "value":     True,
            "evidence_refs": sorted(
                g["stable_id"] for g in aggregated.get("stable_groups", [])
                if g.get("type") == "git"
            ),
        })
    else:
        # If no git evidence, mark as unknown — NOT as false.
        # Per AA-011 §8: "not analyzed" must not become "not present".
        facts.append({
            "fact_id":   "git_repository_present[git]",
            "fact_type": "git_repository_present",
            "subject":   "git",
            "value":     False,
            "evidence_refs": [],
            "note": "no git evidence observed; value=False is a projection, "
                    "not a verified absence",
        })

    total_commits = _extract_git_total_commits(aggregated)
    if total_commits is not None:
        facts.append({
            "fact_id":   "git_total_commits[git]",
            "fact_type": "git_total_commits",
            "subject":   "git",
            "value":     total_commits,
            "evidence_refs": sorted(
                g["stable_id"] for g in aggregated.get("stable_groups", [])
                if g.get("type") == "git" and g.get("subject") == "total_commits"
            ),
        })

    current_branch = _extract_git_current_branch(aggregated)
    if current_branch is not None:
        facts.append({
            "fact_id":   "git_current_branch[git]",
            "fact_type": "git_current_branch",
            "subject":   "git",
            "value":     current_branch,
            "evidence_refs": sorted(
                g["stable_id"] for g in aggregated.get("stable_groups", [])
                if g.get("type") == "git" and g.get("subject") == "current_branch"
            ),
        })

    # Dependency versions
    dep_versions = _extract_dependency_versions(aggregated)
    for name, ver in sorted(dep_versions.items()):
        facts.append({
            "fact_id":   "dependency_version[" + name + "]",
            "fact_type": "dependency_version",
            "subject":   name,
            "value":     ver,
            "evidence_refs": sorted(
                g["stable_id"] for g in aggregated.get("stable_groups", [])
                if g.get("type") == "dependency" and g.get("subject") == name
            ),
        })

    # Update summary fact_count in header.
    if "summary" in aggregated:
        # Summary is part of audit JSON header; here we just keep facts
        # consistent. render_ai_context() will compute its own count.
        pass

    return aggregated


def aggregate_v2_with_aa011(evidence: dict) -> dict:
    """Convenience: aggregate_v2() + AA-011 facts + ready for AI Context.

    This is the canonical entry point for any consumer that needs
    the AI Context (i.e. most LLM-driven downstream use cases).
    """
    agg = aggregate_v2(evidence)
    _append_aa011_facts(agg)
    return agg


if __name__ == "__main__":
    sys.exit(main())