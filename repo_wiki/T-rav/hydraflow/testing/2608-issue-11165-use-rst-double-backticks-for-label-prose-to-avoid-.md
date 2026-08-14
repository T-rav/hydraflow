---
id: 2608
topic: testing
source_issue: 11165
source_phase: plan
created_at: 2026-08-14T19:36:20.069090+00:00
status: active
corroborations: 1
---

# Use RST double-backticks for label prose to avoid grep-guard false positives

Write label names in docstrings and comments using RST double-backticks (``hitl-escalation``), never straight quotes (`"hitl-escalation"`).

- The unification guard in `tests/test_hitl_queue_unification.py` matches quoted string literals to skip prose.
- A comment written with straight quotes trips the guard as if it were a bare literal reintroduced into source.

**Why:** Loosening the regex to skip prose defeats the guard's purpose; converting prose to RST format keeps the guard self-tightening.
