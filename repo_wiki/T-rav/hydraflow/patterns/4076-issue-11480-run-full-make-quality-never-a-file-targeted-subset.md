---
id: 4076
topic: patterns
source_issue: 11480
source_phase: plan
created_at: 2026-08-20T06:54:25.786735+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Run full make quality, never a file-targeted subset (PR #8460 lesson)

Always run the full `make quality` suite, never a file-targeted subset.

**Why:** PR #8460 demonstrated that file-targeted quality runs miss cross-file lint, type, and format interactions that the full suite catches; the cost of a partial run is a reverted PR.
