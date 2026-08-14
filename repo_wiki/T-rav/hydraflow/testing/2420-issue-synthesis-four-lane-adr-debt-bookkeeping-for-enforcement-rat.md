---
id: 2420
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:49.223556+00:00
status: active
corroborations: 1
supersedes: 2230
---

# Four-lane ADR debt bookkeeping for enforcement ratchet updates

When updating ADR-0027 enforcement state, keep four artifacts coherent: `exemptions.md`, the baseline `resolved` count, the `_MISSING_ENFORCEMENT` / `_MISSING_MAX` flags, and the MISSING-branch classifier test. Leave `baseline_snapshot` untouched.

Example: partial updates across these lanes produce false positives or silently weaken the ratchet on the next `make arch-regen`, since the ratchet reads all four together.

**Why:** Partial updates across these lanes produce false positives or silently weaken the ratchet on the next `make arch-regen`.
