---
id: 0752
topic: testing
source_issue: 10434
source_phase: plan
created_at: 2026-07-24T10:19:32.942802+00:00
status: active
corroborations: 1
---

# ADR drift regression tests must assert against the real docs/adr dir, not a fixture

When locking in a citation-granularity fix, write the regression test (see `tests/regressions/test_issue_10411.py` pattern) against the actual `docs/adr/` directory and real ADR file — not a synthetic fixture ADR. Import `compute_drift`/`ADRIndex` from `adr_drift` and assert on real `source_symbols[...]` output.

**Why:** a test built on a fixture ADR can pass while the real ADR still has a stray bare citation (per the collapse rule), giving false confidence that drift is actually fixed.
