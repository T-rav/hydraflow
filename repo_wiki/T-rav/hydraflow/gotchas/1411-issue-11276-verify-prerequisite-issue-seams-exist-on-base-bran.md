---
id: 1411
topic: gotchas
source_issue: 11276
source_phase: plan
created_at: 2026-08-15T21:04:18.934646+00:00
status: active
corroborations: 1
---

# Verify prerequisite issue seams exist on base branch before starting

Before starting work that depends on another issue's code, check that expected files and seams (e.g. `_health_routes.py`, `fixability.py`, `plan_assets`) exist on the base branch. If absent, requeue — never rebuild the seams yourself.

**Why:** Issues may land out of order or be deferred; rebuilding seams silently creates duplicate implementations and merge conflicts.
