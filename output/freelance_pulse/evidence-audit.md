# Evidence Audit — freelance_pulse

- Source schema: `aips-evidence/v1`
- Analyzer: `{'name': 'aips-analyzer', 'version': '0.1.0'}`
- Audit schema: `aips-evidence-audit/v1` v0.1.0
- Analyzed at: 2026-09-04T18:39:18.743837+00:00
- Audit generated at: 2026-09-04T18:39:18.743837+00:00

## 1. Current Evidence Structure

```text
evidence items : 260
metrics        : 67
warnings       : 0
```

Section presence:
- `discovery`: present
- `technology`: present
- `repository`: present
- `dependencies`: present
- `git`: present
- `architecture`: present

Evidence ID range:
- first=E-001, last=E-260, distinct=260/260

## 2. Evidence Type Inventory

| Type | Count |
|------|-------|
| `technology` | 213 |
| `repository_metric` | 42 |
| `git` | 3 |
| `architecture` | 1 |
| `dependency` | 1 |
| _unknown_ | 0 |

## 3. Observation Patterns

### `architecture` — 1 items

Top subjects:
- `cyclic_dependencies`: 1

Signal types:
- `ast_import_graph`: 1

Source methods:
- `ast_import_graph`: 1

Value shapes:
- `list[1]`: 1

### `dependency` — 1 items

Top subjects:
- `requirements_file`: 1

Signal types:
- `file_parse`: 1

Source methods:
- `file_parse`: 1

Source files: 1 distinct
- `requirements.txt`

Value shapes:
- `dict[2]`: 1

### `git` — 3 items

Top subjects:
- `current_branch`: 1
- `first_commit_date`: 1
- `head_commit`: 1

Signal types:
- `git log --reverse`: 1
- `git log -1`: 1
- `git rev-parse --abbrev-ref HEAD`: 1

Source methods:
- `git log --reverse`: 1
- `git log -1`: 1
- `git rev-parse --abbrev-ref HEAD`: 1

Value shapes:
- `string`: 2
- `dict[3]`: 1

### `repository_metric` — 42 items

Top subjects:
- `blank_lines`: 1
- `celery_task_modules`: 1
- `code_lines`: 1
- `comment_lines`: 1
- `css_files`: 1
- `cyclic_dependencies_found`: 1
- `django_apps_found_ast`: 1
- `django_apps_heuristic`: 1
- `git_branches`: 1
- `git_commits`: 1

Signal types:
- `filesystem`: 42

Source methods:
- `filesystem`: 42

Value shapes:
- `int`: 42

### `technology` — 213 items

Top subjects:
- `Django`: 135
- `Tailwind CSS`: 29
- `Bootstrap`: 10
- `Pytest`: 10
- `Alpine.js`: 9
- `HTMX`: 9
- `Celery`: 4
- `Redis`: 2
- `Django DB URL config`: 1
- `Gunicorn`: 1

Signal types:
- `import_pattern`: 144
- `content_pattern`: 59
- `dependency_declaration`: 8
- `file_presence`: 2

Source methods:
- `import_pattern`: 144
- `content_pattern`: 59
- `dependency_declaration`: 8
- `file_presence`: 2

Source patterns (top):
- `import django`: 132
- `class="[^"]*\b(flex|grid|text-\w+|bg-\w+|p-\d+|m-\d+)\b`: 28
- `class="[^"]*\b(container|row|col-|btn|navbar|modal)\b`: 10
- `import pytest`: 10
- `hx-[a-z]+`: 9
- `x-[a-z]+\s*=|Alpine\.js`: 9
- `celery`: 2
- `import celery`: 2
- `redis`: 2
- `dj-database-url`: 1

Source files: 174 distinct
- `api/forms.py`
- `api/settings_views.py`
- `api/templatetags/fp040_extras.py`
- `api/test_i18n.py`
- `api/test_input_translation.py`
- `api/test_navigation_fp028.py`
- `api/test_payment_api.py`
- `api/test_payment_ui.py`
- `api/test_translate.py`
- `api/test_translate_ui.py`
- ...and 164 more files

Value shapes:
- `string`: 213

Sub-groups with >1 occurrence (preserves provenance):
- `Alpine.js` × 9 — 9 files
- `Bootstrap` × 10 — 10 files
- `Celery` × 4 — 4 files
- `Django` × 135 — 133 files
- `HTMX` × 9 — 9 files
- `Pytest` × 10 — 10 files
- `Redis` × 2 — 2 files
- `Tailwind CSS` × 29 — 29 files

## 4. Metrics

Total metrics: 67

By top-level key:
- `discovery`: 36
- `repository`: 31

Examples:
- `discovery.config_flags..gitignore` = True
- `discovery.config_flags.Dockerfile` = False
- `discovery.config_flags.conftest.py` = True
- `discovery.config_flags.docker-compose` = False
- `discovery.config_flags.manage.py` = True

## 5. Provenance

Each evidence item carries `source: {file, section, line, method, pattern}`. This is the unit that links an observation back to where it came from. The contract MUST preserve this link.

Example source structures (one per evidence type):
- `architecture` → source keys: ['method']
- `dependency` → source keys: ['file', 'method']
- `git` → source keys: ['method']
- `repository_metric` → source keys: ['method']
- `technology` → source keys: ['file', 'method', 'pattern']

## 6. Duplication

- exact_duplicate_groups: 0 (would remove 0 items)
- near_duplicate_groups: 1 (would remove 1 items)

Top near-duplicate groups (subject / file / occurrences):
- `technology/Django` [file_presence] @ `manage.py` × 2

## 7. Potential Contract Problems

- IDs `E-NNN` are assigned in analyzer-order; reruns after any analyzer change will reshuffle them. Future contract needs stable IDs.
- `evidence` mixes raw observations (technology, git, architecture) and pre-aggregated metrics (`repository_metric`). They share an evidence shape but have very different semantics.
- `metrics[]` is a flattened name→value list and overlaps with `repository_metric` evidence. Both exist; one of them is redundant.
- `dependencies.python.production[]` carries richer dependency data than the single `dependency` evidence item. Duplicate provenance.
- `architecture.candidate_findings` is interpretive (high fan-in/out, cycles). Currently lives inside an analyzer section, not in evidence[].
- No `unknown` evidence type exists. Future analyzers may emit new types that older contracts do not understand.
- Provenance `source.file` mixes target-relative paths. They are portable but analyzer implementation details (regex patterns) leak into the contract.

## 8. Proposed Evidence Contract v1

The contract is split into three layers. The analyzer keeps emitting the existing `aips-evidence/v1` schema verbatim; the contract defines what the **consumer** sees.

```text
Layer 1 — Observation (raw)
  type, subject, value, source{provenance}, notes

Layer 2 — Evidence (grouped)
  evidence_id = stable hash(type|subject|value|provenance)
  observations = [Observation...]  # never collapsed
  first_seen, last_seen

Layer 3 — Fact (normalized)
  fact_id, fact_type, value, evidence_refs = [evidence_id...]

Layer 4 — Metric (quantitative)
  metric_id, name, value, unit, evidence_refs

Layer 5 — Finding (interpretive, NOT generated by analyzer)
  finding_id, rule, severity, evidence_refs, fact_refs
```

Stable-ID strategy: see Open Questions.

## 9. Migration Considerations

- Phase 1 (this script): compact audit / contract input.
- Phase 2: introduce `evidence_id` (stable hash) as optional field next to existing `id`. Keep `id` for backward compat.
- Phase 3: aggregator pass produces Facts (one per `(type, subject, value)` group). Aggregator is deterministic, runs in the same CLI run.
- Phase 4: Findings live in a separate `findings[]` array and are NOT produced by the analyzer.
- Phase 5: Recovery Engine consumes Facts + Metrics + Findings, never raw observations.

## 10. Open Questions

- Stable-ID hashing: which fields participate? Including `value` makes version bumps produce new IDs; excluding it groups version drift.
- Should `repository_metric` evidence items disappear entirely and become a parallel `metrics[]` (already exists) + `fact` references?
- Should `technology.observations` (which is what deduplication currently targets) be folded into the top-level `evidence[]` only, and de-duplicated there once?
- When does an observation become a Finding candidate vs remain raw? Today `candidate_findings` lives in `architecture` section but other analyzers have similar shapes (high LOC files in `repository.top_10_largest_files`).
- How are we going to version the contract vs version the analyzer? Today both share `0.1.0`; semver implications unclear.
