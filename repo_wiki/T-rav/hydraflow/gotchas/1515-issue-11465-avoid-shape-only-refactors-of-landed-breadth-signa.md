---
id: 1515
topic: gotchas
source_issue: 11465
source_phase: plan
created_at: 2026-08-20T06:26:27.906018+00:00
status: active
corroborations: 1
---

# Avoid shape-only refactors of landed breadth-signal code

Rule: Do not refactor working spray-detection logic into a standalone function (e.g. extracting `_detect_template_spray` from inline code at `src/detector_calibration_loop.py:209-227`) when there is zero behavior change and no future consumer.

The issue's "or equivalent" clause is satisfied by the inline implementation.

**Why:** Post-landing cosmetic refactors carry re-stall risk — the parent #11427 stalled 3 attempts; a reshape with no behavior gain can re-trigger CI failures for no benefit.
