---
id: 2668
topic: testing
source_issue: 11303
source_phase: plan
created_at: 2026-08-16T04:31:48.836033+00:00
status: active
corroborations: 1
---

# Pull sigma multiplier from vitals_methodology, never hardcode

Widened control limits must source their multiplier from `vitals_methodology.widened_sigma_multiplier` (per ADR-0133), never a literal `3.0`.

Pin this with an equality test: at multiplier `3.0` the computed limit must equal the plain 3-sigma value, so any hardcoded regression is visible in CI.

**Why:** Hardcoding the multiplier silently overrides the ADR-0133 widened-limit policy whenever the methodology constant changes, producing tighter or looser bands than the agreed control limit.
