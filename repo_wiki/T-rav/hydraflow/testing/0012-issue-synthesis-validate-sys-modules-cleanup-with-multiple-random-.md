---
id: 0012
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.408876+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Validate sys.modules cleanup with multiple random seeds

Run `pytest --randomly-seed=<N>` with at least two different seeds to confirm that module-level import side effects do not leak between tests.

**Why:** Cleanup failures only surface under specific test orderings; a single seed may never trigger the problematic sequence.
