---
id: 0125
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.601308+00:00
status: superseded
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
superseded_by: 0146
---

# Catch both TimeoutExpired and CalledProcessError — they're siblings

Catch `subprocess.TimeoutExpired` and `subprocess.CalledProcessError` in separate `except` clauses.

Example: `except subprocess.TimeoutExpired: handle_timeout()` followed by `except subprocess.CalledProcessError: handle_failure()`.

**Why:** `TimeoutExpired` is not a subclass of `CalledProcessError`; a single `except CalledProcessError` silently misses timeouts, letting them propagate unhandled.
