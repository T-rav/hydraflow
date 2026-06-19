---
id: 0029
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.317043+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Keep event publishing coupled with the condition that gates it

The `if should_alert:` check and `event_bus.publish(ALERT)` must live in the same method body — never separated into different methods.

Example: inline both in `_check_and_notify()` rather than calling `_check()` then `_publish()`.

**Why:** Separating them creates code paths where the gate is checked but the event isn't fired (or vice versa), breaking observability silently.
