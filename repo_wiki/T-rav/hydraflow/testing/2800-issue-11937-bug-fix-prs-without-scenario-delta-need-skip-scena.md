---
id: 2800
topic: testing
source_issue: 11937
source_phase: plan
created_at: 2026-09-01T09:28:20.470732+00:00
status: active
corroborations: 1
---

# Bug-fix PRs without scenario delta need Skip-Scenario trailer

PRs shaped `fix(...)` with no `tests/scenarios/` delta must include a `Skip-Scenario:` trailer with justification.

Example: `fix(audit): ...` closing #11937 — "rendering-only change in the audit CLI; a MockWorld scenario observes nothing a unit test cannot".

P10.8 demands scenario evidence for bug-fix shapes; the trailer is the documented escape hatch.

**Why:** Omitting the trailer fails P10.8's scenario-evidence requirement on PRs that legitimately have no orchestrator/runner/Port surface to test.
