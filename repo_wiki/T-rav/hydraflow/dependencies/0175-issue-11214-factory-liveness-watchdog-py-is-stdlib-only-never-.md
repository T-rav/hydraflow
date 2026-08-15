---
id: 0175
topic: dependencies
source_issue: 11214
source_phase: plan
created_at: 2026-08-15T05:26:51.324021+00:00
status: active
corroborations: 1
---

# factory_liveness_watchdog.py is stdlib-only, never imports src/

`scripts/factory_liveness_watchdog.py` must never import `src/`. Reuse `scripts/liveness/boot_guard.py` for shared helpers; use only stdlib for HTTP.

- Tests stub `fetch_control_status` — never hit real `:5555`.
- The post-spawn probe must be bounded so the 5-minute tick never blocks.

**Why:** The watchdog runs outside the application package; importing `src/` creates circular or deployment-time failures in a process that must start standalone.
