---
id: 2180
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.400732+00:00
status: active
corroborations: 1
supersedes: 2051
---

# ADR enforcement ratchet: _BASELINE - _RESOLVED grandfathers debt

Use a `_BASELINE - _RESOLVED` ratchet to freeze today's ADR violations and fail only on new ones.

Example: `tests/architecture/test_adr0035_toggle_state_coverage.py` stores existing uncovered toggles in `adr0035_toggle_coverage_baseline.json`; new violations fail CI. ADR-0025's shared-return-type field assertions use the same pattern in `adr0025_field_assertion_baseline.json`. Baselines only shrink.

**Why:** Hard-asserting an unenforced ADR fails hundreds of sites at once, blocking all CI; ratchets let debt shrink incrementally without a flag day.
