---
id: 2728
topic: testing
source_issue: 11355
source_phase: plan
created_at: 2026-08-16T15:26:00.442027+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# RED pin tests must target the rendered payload, not the helper

Rule: Regression pins in `tests/regressions/` should assert against the payload the consumer actually renders, not the underlying helper. For Factory Health popovers, pin `compute_summary(entries, [])["metric_metadata"]`, not the no-arg `metric_metadata()` call.

- Include a counter-pin (e.g. `test_the_pin_tracks_the_computation_not_the_prose`) so prose-only edits can't satisfy the test.

**Why:** Testing the helper but shipping the payload lets divergences between prose and computation slip through the gap.
