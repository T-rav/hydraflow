---
id: 0157
topic: architecture
source_issue: 10310
source_phase: plan
created_at: 2026-07-24T04:15:36.841915+00:00
status: active
corroborations: 1
---

# Cross-module anomaly detector functions in trust_fleet_anomaly_detectors.py must be public

Detector functions added to `src/trust_fleet_anomaly_detectors.py` must not start with `_` even though they're pure/internal helpers, because they're imported by name into `src/trust_fleet_sanity_loop.py` across module boundaries.

Example: `detect_hitl_low_severity_pileup` (not `_detect_hitl_low_severity_pileup`) so `trust_fleet_sanity_loop.py` can import and call it directly.

**Why:** a leading underscore signals module-private intent and breaks the cross-module import the loop relies on; this is a recorded gotcha in `docs/wiki/gotchas.md`.
