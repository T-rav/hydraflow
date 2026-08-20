---
id: 0284
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-18T13:47:37.726708+00:00
status: active
corroborations: 1
supersedes: 0266
---

# factory_liveness_watchdog.py is stdlib-only, never imports src/

`scripts/factory_liveness_watchdog.py` must never import `src/`. Reuse `scripts/liveness/boot_guard.py` for shared helpers; use only stdlib for HTTP.

Example: Tests stub `fetch_control_status` — never hit real `:5555`. The post-spawn probe must be bounded so the 5-minute tick never blocks.

**Why:** The watchdog runs outside the application package; importing `src/` creates circular or deployment-time failures in a process that must start standalone.
