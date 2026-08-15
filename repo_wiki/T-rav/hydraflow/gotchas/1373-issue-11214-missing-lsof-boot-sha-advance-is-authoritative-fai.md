---
id: 1373
topic: gotchas
source_issue: 11214
source_phase: plan
created_at: 2026-08-15T05:26:51.324053+00:00
status: active
corroborations: 1
---

# Missing lsof: boot_sha advance is authoritative, fail closed if unknown

When `lsof` is missing, pid-survival on `:5555` is unprovable. Treat `boot_sha` from `fetch_control_status` as authoritative; fail closed if also unknown.

`find_port_listener_pids` returns empty/unavailable → rely on `boot_sha` match to `git_origin_head` → if boot_sha unknown/unreachable/garbled → return False (no marker, next tick retries, never raises).

**Why:** Assuming heal when you can't prove the old process died leaves a stale-code survivor running on the port undetected.
