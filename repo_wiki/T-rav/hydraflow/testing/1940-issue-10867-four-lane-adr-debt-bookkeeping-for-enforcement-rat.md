---
id: 1940
topic: testing
source_issue: 10867
source_phase: review
created_at: 2026-07-31T10:45:43.194339+00:00
status: active
corroborations: 1
---

# Four-lane ADR debt bookkeeping for enforcement ratchet updates

When updating ADR-0027 enforcement state, keep four artifacts coherent: `exemptions.md`, the baseline `resolved` count, the `_MISSING_ENFORCEMENT` / `_MISSING_MAX` flags, and the MISSING-branch classifier test. Leave `baseline_snapshot` untouched.

**Why:** Partial updates across these lanes produce false positives or silently weaken the ratchet on the next `make arch-regen`, since the ratchet reads all four together.
