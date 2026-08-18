---
id: 2733
topic: testing
source_issue: 11409
source_phase: plan
created_at: 2026-08-18T03:04:36.397144+00:00
status: active
corroborations: 1
---

# Conformance pairs check intersection of declared methods only

Rule: When adding a `(Reference, Fake)` pair to `_REFERENCE_FAKE_PAIRS` in `tests/test_mockworld_fakes_conformance.py`, check signature parity over the **intersection** of declared methods only.

Example: `WikiCompiler` has ~10 public methods (`synthesize_ingest`, `generalize_pair`, …) that `FakeWikiCompiler` deliberately omits — the Port-style "no missing methods" assertion must not apply to partial fakes.

**Why:** Forcing a fake to implement every reference method defeats its purpose as a lightweight I/O-boundary stand-in.
