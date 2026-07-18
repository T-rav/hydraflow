---
id: 0155
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:34:46.626022+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Keep event publishing coupled with the condition that gates it

The `if should_alert:` check and `event_bus.publish(ALERT)` must live in the same method body — never separated into different methods.

Example: inline both in `_check_and_notify()` rather than calling `_check()` then `_publish()`.

**Why:** Separating them creates code paths where the gate is checked but the event isn't fired (or vice versa), breaking observability silently.
