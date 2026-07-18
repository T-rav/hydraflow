---
id: 0071
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:57:29.436818+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Keep event publishing coupled with the condition that gates it

The `if should_alert:` check and `event_bus.publish(ALERT)` must live in the same method body — never separated into different methods.

Example: inline both in `_check_and_notify()` rather than calling `_check()` then `_publish()`.

**Why:** Separating them creates code paths where the gate is checked but the event isn't fired (or vice versa), breaking observability silently.
