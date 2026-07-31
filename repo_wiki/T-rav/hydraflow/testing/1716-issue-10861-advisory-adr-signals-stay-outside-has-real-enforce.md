---
id: 1716
topic: testing
source_issue: 10861
source_phase: plan
created_at: 2026-07-31T01:46:44.758634+00:00
status: active
corroborations: 1
---

# Advisory ADR signals stay outside has_real_enforcement

New ADR-quality signals with high false-negative rates on the live corpus go beside `check_is_tautological` in `src/adr_conformance.py` as advisory predicates, never inside `has_real_enforcement`.

- Attribution signal: 45 of 78 Accepted ADRs cite a test that never names them → folding into REAL flips 45 to WEAK and breaks `tests/test_adr_enforcement_completeness.py`.
- Instead: ratchet via a pinned shrink-only baseline in the test file.

**Why:** The REAL predicate's docstring is explicit that it is non-heuristic; mixing in a 58%-false-negative signal corrupts the published debt report.
