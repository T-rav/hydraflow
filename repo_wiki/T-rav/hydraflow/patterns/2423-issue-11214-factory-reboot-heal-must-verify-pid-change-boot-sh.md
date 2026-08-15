---
id: 2423
topic: patterns
source_issue: 11214
source_phase: plan
created_at: 2026-08-15T05:26:51.323996+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Factory reboot heal must verify PID change + boot_sha before marking success

A factory reboot is healed only when the port owner PID changed AND `fetch_control_status` reports a `boot_sha` at/after `git_origin_head`. Never stamp `stale_reboot_at` on `Popen` return alone.

`reboot_factory` → spawn → bounded probe (`find_port_listener_pids` + `fetch_control_status`) → stamp marker only on verified match. Unverified → return False, write no marker, re-signal survivor once, notify with surviving PID + unchanged boot_sha.

**Why:** Popen succeeding doesn't prove the old process released `:5555` or the new one reached the target sha — a "healed on hope" hole leaves stale code running.
