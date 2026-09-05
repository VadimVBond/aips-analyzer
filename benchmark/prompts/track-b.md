# Track B Prompt — AIPS + LLM Project Analysis

You are conducting a **Project Analysis** of a software repository.

## Project

- **Repository:** `K:\PROJECTS\Astro\0 GitHub\AI-Freelance\freelance_pulse`
- **Commit:** see `benchmark/metadata.json` (fixed for this run)
- **Files available:** full repository, normal filesystem access (read, grep, find, etc.)

## AIPS AI Context

In addition to the repository, you have a **deterministic AI Context**
produced by AIPS (Automated Project Intelligence System) for this exact
commit. The AI Context is in:

- `K:\PROJECTS\Astro\0 GitHub\AI-Freelance\aips-analyzer\output\freelance_pulse\evidence-ai-context.json`

You may also have the full AIPS output:

- `output\freelance_pulse\evidence-aggregated.json` (stable groups, facts, metrics, unknowns)

### What the AIPS AI Context is

- A **deterministic preprocessing** of the repository, computed at
  the fixed commit.
- Contains: `facts[]` (canonical, deduplicated), `metrics[]`,
  `stable_groups_sample[]` (top 5), `unknowns[]` (items AIPS couldn't
  classify), `summary`, `limits` (analyzer caps), `guidance_for_llm`.
- Each fact has a `fact_id` (e.g. `technology_present[Django]`) and
  `evidence_refs[]` pointing to specific stable_groups.

### What the AIPS AI Context is NOT

- **NOT** a complete replacement for the repository. It is a
  *summary*. You still have repository access — you can read any
  file, grep, etc.
- **NOT** ground truth. It may be incomplete, or contain errors
  (AIPS has bugs). Verify claims against the source code when
  possible.
- **NOT** a fixed contract. It is a *layer* you can use to make
  your analysis faster and more grounded, but you are not required
  to use it.

## Your Task

Produce a **Project Analysis Report** in free-form text covering the
following dimensions, where applicable. For each claim, you SHOULD
cite either an AIPS `fact_id` (e.g. `technology_present[Django]`) or a
file:line from the repository. If you cannot verify a claim, say so
explicitly.

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

- Use **only** information you can verify from the AI Context or the
  repository.
- Do **not** invent numbers. If you can't measure, say so.
- For every substantive claim, **cite** either the AIPS `fact_id` or
  the file:line that supports it.
- If the AI Context says `unknown[]` for something, treat it as a
  fact: it is unknown. Do **NOT** claim it as absent without
  explicit evidence.
- If the AI Context is wrong, you can disagree — but cite the
  source code that contradicts it.
- Be honest about gaps. This is more valuable than fabricated confidence.

## Difference vs. Track A

You have an **additional** structured input (AIPS AI Context).
The repository is the same. The only difference is the *presence*
of AIPS preprocessing as a starting point.

You are **not** restricted to the AI Context. You have full
repository access. You can use the AI Context to:
- **Pre-check** what AIPS found (e.g. `technology_present[Django]`),
  then verify against source code.
- **Discover** facts AIPS has already extracted (saves time vs.
  re-deriving from scratch).
- **Identify gaps** in `unknowns[]` and explicitly address them
  (e.g. "AIPS marked `total_commits` as unknown; I checked git log
  and found 38 commits").

## Output

A single free-form Project Analysis Report. No specific JSON schema.
Structure it as you find natural, but ensure all 13 dimensions above
are addressed (or explicitly marked as not analyzable).

## Tools available

- File reading
- grep / find / search
- git CLI (read-only)
- Standard filesystem operations
- Read AIPS outputs (AI Context, aggregated evidence)
