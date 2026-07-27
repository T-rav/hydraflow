---
id: 1342
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:47:42.324612+00:00
status: active
corroborations: 1
supersedes: 1268
---

# ADR-citation drift fixes skip MockWorld/e2e — static check

For ADR-citation drift fixes (pure ADR-text plus a static test over a side-effect-free regex parser like _SOURCE_FILE_CITATION_RE), skip MockWorld scenario and sandbox e2e layers despite the repo's usual three-layer pyramid requirement.

Example: the change crosses no pipeline phase, runner, or Port — it has no runtime surface for MockWorld or e2e to exercise. See also: Doc+single-unit-test fixes skip MockWorld/e2e.

**Why:** Load-bearing-feature test-pyramid rules apply to features that touch runtime behavior; a text/static-analysis-only fix has no runtime surface, so skipping those layers isn't a shortcut.
