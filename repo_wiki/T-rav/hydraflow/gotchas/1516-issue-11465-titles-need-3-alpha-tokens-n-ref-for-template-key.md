---
id: 1516
topic: gotchas
source_issue: 11465
source_phase: plan
created_at: 2026-08-20T06:26:27.906026+00:00
status: active
corroborations: 1
---

# Titles need ≥3 alpha tokens + #N ref for template_key

Rule: Issue titles used in detector calibration spray tests must contain ≥3 alpha tokens and at least one `#N` reference, or `template_key()` at `src/detector_calibration_loop.py:88` will not produce a distinct key.

Example: `"HITL: trust-loop anomaly wA for #9001"` passes; `"anomaly #9001"` does not.

**Why:** Spray grouping relies on `template_key` producing distinct keys per template; malformed titles collapse into the same key and silently merge independent scenarios.
