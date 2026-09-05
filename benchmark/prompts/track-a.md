# Track A Prompt — Direct LLM Project Analysis

You are conducting a **Project Analysis** of a software repository.

## Project

- **Repository:** `K:\PROJECTS\Astro\0 GitHub\AI-Freelance\freelance_pulse`
- **Commit:** see `benchmark/metadata.json` (fixed for this run)
- **Files available:** full repository, normal filesystem access (read, grep, find, etc.)

## Your Task

Produce a **Project Analysis Report** in free-form text covering the
following dimensions, where applicable. For each claim, you SHOULD
cite the file:line or path that supports it. If you cannot verify a
claim, say so explicitly ("I don't know" / "Not analyzed" / "Requires
runtime" — do NOT fabricate).

### Dimensions

1. **Project Overview** — what is this project? (1-3 sentences)
2. **Technology Stack** — primary languages, frameworks, key libraries
3. **Repository Metrics** — total files, Python files, test files, etc.
4. **Dependencies** — production deps (with versions if known)
5. **Git State** — current branch, total commits, contributors
6. **Architecture** — Django apps, modules with high fan-in/fan-out,
   cyclic dependencies, parse errors
7. **Tests** — test framework, test file count, coverage if measurable
8. **Migrations** — migration directory presence
9. **Configuration** — pyproject.toml, requirements.txt, package.json, etc.
10. **Web/SEO** (if observable) — robots.txt, sitemap, basic HTML signals
11. **Major Risks** — what looks risky, missing, or unclear
12. **Important Unknowns** — what you cannot determine from static analysis
13. **Recommended Next Steps** — specific actions a developer could take

## Constraints

- Use **only** information you can verify by reading the repository.
- Do **not** invent numbers. If you can't measure, say so.
- For every substantive claim, **cite** the supporting file:line or path.
- If a dimension requires runtime (e.g. "does the test suite pass?"), say
  "Requires runtime" — do not guess.
- Be honest about gaps. This is more valuable than fabricated confidence.
- Do not make recommendations that depend on information you don't have.

## Output

A single free-form Project Analysis Report. No specific JSON schema.
Structure it as you find natural, but ensure all 13 dimensions above
are addressed (or explicitly marked as not analyzable).

## What you do NOT have

- AIPS AI Context.
- Pre-computed facts/metrics.
- Any pre-processing.

You start from the raw repository only. This is the "Direct LLM"
baseline — what a typical AI coding agent would produce when given
raw repository access and a project analysis task.

## Tools available

- File reading
- grep / find / search
- git CLI (read-only)
- Standard filesystem operations
