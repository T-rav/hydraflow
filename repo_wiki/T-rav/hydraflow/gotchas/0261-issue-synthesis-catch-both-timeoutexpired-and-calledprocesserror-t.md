---
id: 0261
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.026543+00:00
status: superseded
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
superseded_by: 0282
---

# Catch both TimeoutExpired and CalledProcessError — they're siblings

Catch `subprocess.TimeoutExpired` and `subprocess.CalledProcessError` in separate `except` clauses.

Example: `except subprocess.TimeoutExpired: handle_timeout()` followed by `except subprocess.CalledProcessError: handle_failure()`.

**Why:** `TimeoutExpired` is not a subclass of `CalledProcessError`; a single `except CalledProcessError` silently misses timeouts, letting them propagate unhandled.
