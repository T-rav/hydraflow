---
id: 2631
topic: testing
source_issue: 11202
source_phase: plan
created_at: 2026-08-15T03:13:32.213252+00:00
status: active
corroborations: 1
---

# ADR Enforced-by citations use file-only pytest:path form

ADRs in `docs/adr/` cite their enforcing test in file-only form: `pytest:tests/architecture/test_no_ignored_active_tests.py`. The ADR conformance suite (`tests/architecture/test_adr_enforcement_ratchet.py`) verifies each citation resolves to a real, asserting, non-mutating check. When editing an ADR's Enforced-by section, re-run the ratchet test for blast radius.

**Why:** Inconsistent citation forms (e.g., class-qualified or function-qualified paths) break the conformance suite and make enforcement unverifiable across the ADR set.
