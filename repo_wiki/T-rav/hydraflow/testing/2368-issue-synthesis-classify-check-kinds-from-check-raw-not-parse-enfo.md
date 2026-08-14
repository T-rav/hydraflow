---
id: 2368
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.152027+00:00
status: superseded
corroborations: 1
supersedes: 2228
superseded_by: 2557
---

# Classify check kinds from Check.raw, not parse_enforced_by

Classify check kinds (`pytest`/`make`/`script`/`prose`/`other`) from `Check.raw` inside `src/setpoint/density.py`. Do not widen `adr_index.parse_enforced_by` to carry a kind axis.

**Why:** `parse_enforced_by` is shared across conformance paths; widening it ripples into every caller and risks regressions in `evaluate_adrs`. The acceptance criteria pin `parse_enforced_by` as unchanged.
