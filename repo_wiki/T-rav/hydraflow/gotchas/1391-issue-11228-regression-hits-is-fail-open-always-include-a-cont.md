---
id: 1391
topic: gotchas
source_issue: 11228
source_phase: plan
created_at: 2026-08-15T07:17:21.034742+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# regression_hits is fail-open; always include a control issue in guards

Tests that call `regression_hits` must include a control issue known to be encoded alongside the target.

- `regression_hits` returns `()` both when no match exists and when `git` itself fails
- Without a control, a broken checkout reads as "unencoded" instead of erroring
- Guard pattern: assert hits ≥1 for the target escape AND ≥1 for a known-encoded control issue

**Why:** Fail-open behavior collapses git failure and no-match into the same `()` return, so a missing control lets breakages pass silently.
