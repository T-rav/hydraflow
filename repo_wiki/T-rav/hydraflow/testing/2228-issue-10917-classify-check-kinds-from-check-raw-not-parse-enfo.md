---
id: 2228
topic: testing
source_issue: 10917
source_phase: plan
created_at: 2026-07-31T16:16:35.877465+00:00
status: active
corroborations: 1
---

# Classify check kinds from Check.raw, not parse_enforced_by

Classify check kinds (`pytest`/`make`/`script`/`prose`/`other`) from `Check.raw` inside the new `src/setpoint/density.py` module. Do not widen `adr_index.parse_enforced_by` to carry a kind axis. **Why:** `parse_enforced_by` is shared across conformance paths; widening it ripples into every caller and risks regressions in `evaluate_adrs`. The acceptance criteria pin `parse_enforced_by` as unchanged.
