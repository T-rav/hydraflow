---
id: 0894
topic: patterns
source_issue: 10820
source_phase: plan
created_at: 2026-07-31T00:58:39.724660+00:00
status: active
corroborations: 1
---

# ConvergenceOscillationLoop label doesn't exist; use fleet-level series

`ConvergenceOscillationLoop` never fired 07-14..07-28 — its label doesn't exist and there's no ledger history. Build series 3 fleet-level from label timelines rather than per-item, and record the absence as confirming the fleet-level hypothesis.

- Per-item query for a non-existent label returns empty silently
- Fleet-level label timelines surface the gap explicitly

**Why:** Per-item telemetry for a loop whose label was never applied would silently return empty data, masking the loop's actual flux contribution.
