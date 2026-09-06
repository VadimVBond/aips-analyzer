# AIPS Analyzer

**Version:** 0.1.0
**Status:** Stable — production-ready deterministic engine

---

## What is AIPS Analyzer?

AIPS Analyzer is a **deterministic static analysis engine** for software projects.

Given a project directory, one command produces a complete analysis package containing:
- raw evidence
- normalized facts and metrics
- AI Context (ready for an external LLM)
- human-readable audit
- portable manifest

The analyzer itself does **not** interpret the data. Interpretation,
prioritization, and recommendations are the responsibility of an external LLM.

---

## What it analyzes

| Analyzer | Description |
|----------|-------------|
| **Discovery** | File counts, types, directory structure, Django app heuristics |
| **Technology** | Technology signals from dependency files, imports, HTML patterns |
| **Repository** | LOC metrics, code/comment/blank line ratios per language |
| **Dependencies** | Python (pyproject.toml, requirements.txt, Pipfile) and Node (package.json) |
| **Git** | Commits, branches, contributors, top changed files, commit activity |
| **Architecture** | Python AST: import graph, cyclic deps, fan-in/fan-out, Django apps |

---

## What it does NOT do

```
Current version does not use AI.
Current version does not execute analyzed project code.
Current version does not provide a web UI.
```

Specifically:
- ❌ No AI/LLM (no OpenAI, Claude, Gemini, Ollama, etc.)
- ❌ No Flask or web interface
- ❌ No `pip install`, `npm install`, `pytest`, `manage.py`, `setup.py`
- ❌ No `git checkout`, `git pull`, `git reset`, `git clean`
- ❌ No import or execution of the analyzed project's modules

---

## How to run

### Install
```bash
pip install -e .
# or for development:
pip install -e ".[dev]"
```

### Analyze a project
```bash
aips-analyze /path/to/your/project
# or:
python -m aips_analyzer /path/to/your/project
```

### Options
```bash
# Custom output directory
aips-analyze /path/to/project --output ./my_results

# Verbose logging
aips-analyze /path/to/project --verbose

# Print only (no files)
aips-analyze /path/to/project --no-output
```

---

## Generated files

The analyzer produces a complete package under `output/<project-name>/`:

```
output/<project>/
├── evidence.json              ← raw observations (aips-evidence/v1)
├── evidence-aggregated.json   ← normalized facts + metrics (aips-evidence-audit/v2)
├── evidence-ai-context.json   ← LLM-ready projection (aips-ai-context/v1)
├── evidence-audit.md           ← human-readable audit (aips-evidence-audit/v1)
└── manifest.json              ← package manifest (aips-manifest/v1)
```

### Artifact guide

| Artifact | Schema | Purpose |
|----------|--------|---------|
| `evidence.json` | `aips-evidence/v1` | Raw evidence: atomic observations with provenance |
| `evidence-aggregated.json` | `aips-evidence-audit/v2` | **Facts** (deduplicated observations) + **canonical metrics** |
| `evidence-ai-context.json` | `aips-ai-context/v1` | Structured input for an external LLM |
| `evidence-audit.md` | `aips-evidence-audit/v1` | Human-readable summary of the evidence contract |
| `manifest.json` | `aips-manifest/v1` | Package metadata, schema versions, artifact hashes |

### Key distinctions

**Evidence** — raw observations: "Django signal found in pyproject.toml [dependencies]"
**Facts** — normalized, deduplicated evidence with stable IDs: one fact per unique observation
**Metrics** — quantitative measurements: file counts, LOC, commit counts, fan-in/out
**Unknowns** — evidence types the aggregator does not yet recognize
**AI Context** — the complete structured view intended for an LLM. It contains facts, metrics, unknowns, and guidance on how to interpret them

**Important:** The existence of a fact does **not** imply correctness, severity, or actionability. The analyzer records what it observed. Interpretation is the LLM's responsibility.

---

## Example output

```
================================================================
  AIPS Analyzer  v0.1.0
================================================================

  Project  : freelance_pulse
  Analyzed : 2026-09-06T18:12:00+00:00
  Duration : 4.2s

  ── Summary ──────────────────────────────────────
  Total files       : 247
  Python files      : 184
  Test files        : 23
  Total LOC         : 14823
  Python modules    : 89
  Git available     : True
  Git branch        : main
  Architecture mods : 134
  Cyclic deps       : 2
  Evidence items    : 54
  Warnings          : 0

  ── Output package ──────────────────────────────
  evidence.json                output/freelance_pulse/evidence.json
  evidence-aggregated.json     output/freelance_pulse/evidence-aggregated.json
  evidence-ai-context.json    output/freelance_pulse/evidence-ai-context.json
  evidence-audit.md            output/freelance_pulse/evidence-audit.md
  manifest.json                output/freelance_pulse/manifest.json

  Manifest schema: aips-manifest/v1 v0.1.0

  Analysis completed successfully.
```

---

## Determinism

The analyzer is deterministic: two runs of the same analyzer version
against the same project state produce semantically identical artifacts.
The only intentionally non-deterministic fields are:

- `project.analyzed_at` — wall-clock timestamp
- `project.analysis_duration_seconds` — execution time
- `manifest.generated_at` — when the manifest was written

These are explicitly classified as volatile metadata.

---

## Safety limitations

- Reads files only — no write operations
- Does not import analyzed project modules (uses `ast.parse` only)
- Does not execute shell commands from analyzed projects
- Git commands are read-only (`git log`, `git status`, `git branch -a`, etc.)
- Exclusion lists prevent scanning `.venv`, `node_modules`, `__pycache__`, etc.

---

## Architecture

```
aips_analyzer/
├── analyzer.py          ← Orchestrator: runs all analyzers, isolates failures
├── models.py           ← Data models (EvidenceItem, ArchitectureModule, etc.)
├── evidence.py          ← EvidenceBuilder with auto-incrementing E-001, E-002...
├── manifest.py          ← Deterministic manifest.json writer
├── constants.py         ← Centralized exclusions, file type maps
├── analyzers/
│   ├── discovery.py    ← Filesystem traversal
│   ├── technology.py    ← Technology signal detection
│   ├── repository.py    ← LOC metrics
│   ├── dependencies.py  ← Dependency file parsing
│   ├── git.py          ← Read-only Git CLI
│   └── architecture.py  ← Python AST analysis
└── cli/
    └── main.py         ← CLI entry point
```

### Canonical pipeline (v0.1)

```
target project
    ↓
Analyzer (6 analyzers, isolated failures)
    ↓
evidence.json  (aips-evidence/v1)
    ↓
Aggregator v2  (stable_id/display_key, facts, canonical_metrics, unknowns)
    ↓
evidence-aggregated.json  (aips-evidence-audit/v2)
    ↓
AI Context renderer
    ↓
evidence-ai-context.json  (aips-ai-context/v1)
    + evidence-audit.md    (human-readable audit)
    + manifest.json        (package manifest)
```

---

## Running tests

```bash
pytest tests/ -v
```

Current test count: **164 tests** (all passing).

---

## Design principles

- Each analyzer is **independent** — one failure does not stop others
- All results include **provenance** (source file, section, method)
- Technology detection records **observations**, not conclusions
- The engine can be called from CLI, Flask, Celery, or API
- **No assumptions are made** — unavailable information is explicit, not fabricated
