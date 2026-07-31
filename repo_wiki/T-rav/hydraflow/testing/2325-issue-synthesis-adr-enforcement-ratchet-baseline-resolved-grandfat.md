---
id: 2325
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.035269+00:00
status: active
corroborations: 1
supersedes: 2180
---

# ADR enforcement ratchet: _BASELINE - _RESOLVED grandfathers debt

Use a `_BASELINE - _RESOLVED` ratchet to freeze today's ADR violations and fail only on new ones.

Example: `tests/architecture/test_adr0035_toggle_state_coverage.py` stores existing uncovered toggles in `adr0035_toggle_coverage_baseline.json`; new violations fail CI. Baselines only shrink.

**Why:** Hard-asserting an unenforced ADR fails hundreds of sites at once, blocking all CI; ratchets let debt shrink incrementally without a flag day.
