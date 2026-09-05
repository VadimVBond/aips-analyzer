# Benchmark Results — AA-018 (Summary)

**Date:** 2026-09-04
**Project:** `freelance_pulse` @ `1a1411edbf27f285a16ee9db8cc05726299dcb25`
**Model:** deterministic-llm-proxy-v1 (no external LLM API)
**Tracks:** 2 (A: Direct LLM, B: AIPS + LLM)
**Runs:** 3 per track (proxy deterministic; byte-identical outputs)

---

## Run variance

| Run | Track A (hash) | Track B (hash) |
|---|---|---|
| 1 | identical | identical |
| 2 | identical | identical |
| 3 | identical | identical |

**Note:** Proxy is deterministic. Real LLM variance is expected to be
non-zero but cannot be measured without API access.

## Deterministic AIPS variance

The AIPS layer (evidence → aggregator → AI Context) is **byte-identical**
across runs for the same commit. Confirmed by:
- `output\freelance_pulse\evidence.json` — same hash across runs.
- `output\freelance_pulse\evidence-aggregated.json` — same hash.
- `output\freelance_pulse\evidence-ai-context.json` — same hash.

## Hypothesis verdicts (H1-H6)

| H | Verdict | Note |
|---|---|---|
| H1 | **SUPPORTED** | Track B had 25 correct, Track A had 11. |
| H2 | **SUPPORTED** | Track B hallucination = 0; Track A = 0.08. |
| H3 | **INCONCLUSIVE** in POC | Proxy = deterministic; both = 0. |
| H4 | **SUPPORTED** | Track B evidence traceability 0.73; Track A 0.32. |
| H5 | **SUPPORTED** | Track B input ~10x smaller. |
| H6 | **SUPPORTED** (proxy) | Track B review ~50% faster. |
| H7-H9 | **NOT TESTED** | See benchmark doc §1.3. |

## Where Direct LLM wins (Track A)

- Lower upfront setup (no AIPS pipeline first).
- Larger context window (can read everything; Track B constrained
  by AI Context).
- Adversarial robustness (AIPS is static; Track A sees fresh repo).

## Where AIPS wins (Track B)

- **Accuracy:** 100% vs 85% (zero hallucinations vs 2).
- **Evidence traceability:** 73% vs 32%.
- **Token cost:** ~10x reduction.
- **Human verification time:** ~50% reduction.
- **Honest gap handling:** explicit "NOT IN AI CONTEXT" instead of
  guessing.
- **Determinism:** AIPS layer byte-identical for same commit.
- **Reproducibility:** AI Context canonical, another LLM sees same input.

## Final decision (AA-018 §15)

**B — AIPS provides measurable improvement on some dimensions.**

Track B (AIPS + LLM) is **materially better** than Track A (Direct LLM)
on:
- accuracy (correct / (correct + incorrect))
- unsupported_claim_rate
- hallucination_rate (incorrect AND unsupported)
- evidence_traceability
- input token cost
- human verification time

Track A is **not** materially worse on any measured dimension in this
POC. Track A could be considered for lower-upfront-cost scenarios
where AIPS pipeline setup is not justified.

## Next steps (max 3, per AA-018 §15)

1. **Re-run with a real LLM API** (e.g. Claude Sonnet, GPT-4 Turbo).
   Required to measure real variance and confirm proxy results.
   ~1 day of human effort + LLM API budget.

2. **Add a second project** to validate generalization beyond
   freelance_pulse. Candidate: a small Python library, or a different
   Python web framework (Flask/FastAPI). Same methodology.

3. **Build AIPS Mode B (Local Runtime)** to address G-036/G-037 (the
   two AIPS coverage signals). After Mode B, AIPS could surface
   `total_commits` and per-package `dependency_version` as facts.

## Limitations

- N=1 project, N=3 runs (with deterministic proxy), AI reviewer.
- Proxy is not a real LLM. Results are suggestive, not conclusive.
- Real LLM variance not measured.
- H7-H9 not tested (require second LLM, second commit, multiple
  report types).

See full report in `AA-018_BENCHMARK_REPORT.md` (in `.ai/`).
See per-claim scoring in `benchmark/scoring.md`.
