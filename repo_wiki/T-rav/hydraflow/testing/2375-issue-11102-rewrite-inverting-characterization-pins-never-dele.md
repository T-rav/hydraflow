---
id: 2375
topic: testing
source_issue: 11102
source_phase: plan
created_at: 2026-08-14T07:12:44.487628+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Rewrite inverting characterization pins, never delete them

When a regression test asserts a defect exists (e.g. `test_gen_gates_check_cannot_see_prose_drift` asserting `"**2 required checks" in regenerated`), fixing the defect inverts the pin to RED. Rewrite it to characterize the behavior generically — do not delete it.

- Re-scope to assert the splicer round-trips prose outside markers untouched, without pinning the literal stale string.
- Delegate count assertions to the shared `validate_prose_counts` predicate rather than re-deriving the comparison inline.

**Why:** Deleting the pin discards the documentation of *why* the drift was permanent; rewriting preserves the guard and the institutional memory.
