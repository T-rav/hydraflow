---
id: 4070
topic: patterns
source_issue: 11442
source_phase: plan
created_at: 2026-08-18T08:00:27.527794+00:00
status: active
corroborations: 1
---

# Place hosted actuators before host early-return gates in _do_work

When wiring a hosted actuator into a loop's `_do_work`, insert the `await` AFTER the enabled/config/dry_run gates but BEFORE any `_resolve_range` call or `no_new_commits`/`cursor_primed` early returns. In `ErosionMetricsLoop._do_work`, early returns skip everything after them — a drift check placed after the cursor gate would be silently skipped on quiet days.

**Why:** The actuator's trigger condition (drift in telemetry) is independent of the host's commit cursor; gating it on commit activity would miss drift episodes.
