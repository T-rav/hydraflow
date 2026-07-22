---
id: 0227
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.797283+00:00
status: superseded
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
superseded_by: 0248
---

# Catch both TimeoutExpired and CalledProcessError — they're siblings

Catch `subprocess.TimeoutExpired` and `subprocess.CalledProcessError` in separate `except` clauses.

Example: `except subprocess.TimeoutExpired: handle_timeout()` followed by `except subprocess.CalledProcessError: handle_failure()`.

**Why:** `TimeoutExpired` is not a subclass of `CalledProcessError`; a single `except CalledProcessError` silently misses timeouts, letting them propagate unhandled.
