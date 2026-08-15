---
id: 2241
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T01:03:09.798643+00:00
status: active
corroborations: 1
supersedes: 2125
---

# ConvergenceOscillationLoop label doesn't exist; use fleet-level series

`ConvergenceOscillationLoop` never fired 07-14..07-28 — its label doesn't exist and there's no ledger history. Build series 3 fleet-level from label timelines rather than per-item, and record the absence as confirming the fleet-level hypothesis.

Example: Per-item query for a non-existent label returns empty silently; fleet-level label timelines surface the gap explicitly.

**Why:** Per-item telemetry for a loop whose label was never applied would silently return empty data, masking the loop's actual flux contribution.
