---
id: 1235
topic: gotchas
source_issue: 10883
source_phase: plan
created_at: 2026-07-31T07:40:16.907020+00:00
status: active
corroborations: 1
---

# Differentiate chronic timeouts from suspected hangs in GateHealthLoop

In `src/gate_health_loop.py`, when `find_suspected_hangs` detects the same check cancelled at timeout in ≥2 runs, emit `kind="chronic_timeout"`.
- Key `finding_fingerprint` on `kind:check` (excluding run id)
- Point issue body at capacity, not `killpg`

**Why:** Prevents over-budget capacity issues from fanning out into a new `suspected_hang` issue per push and mislabeling the root cause.
