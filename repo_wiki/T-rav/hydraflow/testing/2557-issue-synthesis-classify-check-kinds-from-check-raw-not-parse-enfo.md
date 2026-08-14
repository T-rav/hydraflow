---
id: 2557
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.429296+00:00
status: active
corroborations: 1
supersedes: 2368
---

# Classify check kinds from Check.raw, not parse_enforced_by

Classify check kinds (`pytest`/`make`/`script`/`prose`/`other`) from `Check.raw` inside `src/setpoint/density.py`. Do not widen `adr_index.parse_enforced_by` to carry a kind axis.

**Why:** `parse_enforced_by` is shared across conformance paths; widening it ripples into every caller and risks regressions in `evaluate_adrs`. The acceptance criteria pin `parse_enforced_by` as unchanged.
