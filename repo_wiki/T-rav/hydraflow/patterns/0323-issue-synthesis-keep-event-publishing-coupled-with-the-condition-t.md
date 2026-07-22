---
id: 0323
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:37:54.875069+00:00
status: active
corroborations: 1
supersedes: 0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294,0295,0296,0297,0298,0299,0300,0301
---

# Keep event publishing coupled with the condition that gates it

The `if should_alert:` check and `event_bus.publish(ALERT)` must live in the same method body — never separated into different methods.

Example: Inline both in `_check_and_notify()` rather than calling `_check()` then `_publish()`.

**Why:** Separating them creates code paths where the gate is checked but the event isn't fired (or vice versa), breaking observability silently.
