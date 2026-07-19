---
id: 0239
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.225134+00:00
status: active
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
---

# Keep event publishing coupled with the condition that gates it

The `if should_alert:` check and `event_bus.publish(ALERT)` must live in the same method body — never separated into different methods.

Example: Inline both in `_check_and_notify()` rather than calling `_check()` then `_publish()`.

**Why:** Separating them creates code paths where the gate is checked but the event isn't fired (or vice versa), breaking observability silently.
