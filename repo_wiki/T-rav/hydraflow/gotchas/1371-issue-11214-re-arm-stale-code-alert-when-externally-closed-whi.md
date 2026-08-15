---
id: 1371
topic: gotchas
source_issue: 11214
source_phase: plan
created_at: 2026-08-15T05:26:51.324038+00:00
status: active
corroborations: 1
---

# Re-arm stale-code alert when externally closed while condition persists

`_check_stale_code` in `src/health_monitor_loop.py` must not gate solely on its dedup key. Require an actually-open alert while the stale condition persists; if the alert was externally closed while still stale, re-file at most one per tick.

- Still stale + alert open → dedup holds, file nothing.
- Still stale + alert closed → re-file, body notes prior closure.
- Label-listing failure → stay silent, never re-file blind.

**Why:** A dedup key alone makes an externally-closed alert look "addressed" when the underlying stale-code condition never resolved.
