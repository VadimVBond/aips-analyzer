# AIPS Analyzer

**Version:** 0.1.0  
**Status:** Prototype — Deterministic Engine only

---

## What is AIPS Analyzer?

AIPS Analyzer is a **deterministic static analysis engine** for software projects.

It reads a project directory and produces a structured `evidence.json` file
containing raw observations about the project — its structure, technologies,
dependencies, Git history, and architecture.

This is the **foundation** of the AIPS (AI-Powered Software Audit) system.

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

### Run on a project
```bash
# Option 1: python -m
python -m aips_analyzer /path/to/your/project

# Option 2: CLI command (after pip install -e .)
aips-analyze /path/to/your/project

# With custom output directory
aips-analyze /path/to/your/project --output ./my_results

# With verbose logging
aips-analyze /path/to/your/project --verbose
```

### Output
```
output/
└── <project_name>/
    ├── evidence.json   ← main output
    └── run.log         ← analysis log
```

---

## Output format

```json
{
  "schema": "aips-evidence/v1",
  "analyzer": { "name": "aips-analyzer", "version": "0.1.0" },
  "project": { "name": "...", "root": "...", "analyzed_at": "..." },
  "discovery": { "total_files": 247, "python_files_count": 184, ... },
  "technology": { "observations": [...], "technology_signals": {...} },
  "repository": { "total_lines": 14823, "code_lines": 9241, ... },
  "dependencies": { "python": {...}, "node": {...} },
  "git": { "available": true, "total_commits": 312, ... },
  "architecture": { "django_apps": [...], "cyclic_dependencies": {...}, ... },
  "evidence": [
    {
      "id": "E-001",
      "type": "technology",
      "subject": "Django",
      "value": "manage.py present",
      "source": { "file": "manage.py", "method": "file_presence" }
    },
    ...
  ],
  "warnings": []
}
```

---

## Architecture

```
aips_analyzer/
├── analyzer.py          ← Orchestrator: runs all analyzers, isolates failures
├── models.py            ← Data models (EvidenceItem, ArchitectureModule, etc.)
├── evidence.py          ← EvidenceBuilder with auto-incrementing E-001, E-002...
├── constants.py         ← Centralized exclusions, file type maps
└── analyzers/
    ├── discovery.py     ← Filesystem traversal
    ├── technology.py    ← Technology signal detection (observations, not verdicts)
    ├── repository.py    ← LOC metrics
    ├── dependencies.py  ← Dependency file parsing
    ├── git.py           ← Read-only Git CLI
    └── architecture.py  ← Python AST analysis
```

### Design principles
- Each analyzer is **independent** — one failure does not stop others
- All results include **provenance** (source file, section, method)
- Technology detection records **observations**, not conclusions
- The engine (`analyze_project()`) can be called from CLI, Flask, Celery, or API

---

## Safety limitations

- Reads files only — no write operations
- Does not import analyzed project modules (uses `ast.parse` only)
- Does not execute shell commands from analyzed projects
- Git commands are read-only (`git log`, `git status`, `git branch -a`, etc.)
- Exclusion lists prevent scanning `.venv`, `node_modules`, `__pycache__`, etc.

---

## Running tests

```bash
pytest tests/ -v
```

---

## Future integration

The `analyze_project(path)` function is designed to be called from:
- CLI (current)
- Flask web UI (next phase)
- Celery background task (future)
- REST API (future)

After obtaining a valid `evidence.json`, an AI layer will be introduced
to interpret the evidence and generate findings. The AI never sees raw code —
only the structured evidence.
