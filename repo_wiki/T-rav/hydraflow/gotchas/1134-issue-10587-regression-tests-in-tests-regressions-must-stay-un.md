---
id: 1134
topic: gotchas
source_issue: 10587
source_phase: plan
created_at: 2026-07-26T02:52:52.792545+00:00
status: superseded
corroborations: 1
superseded_by: 1144
---

# Regression tests in tests/regressions/ must stay unmodified as acceptance gates

For issue #10587, `tests/regressions/test_issue_10587.py` was written red-first (2 failing exemption assertions, 1 passing control) before the plan phase and is the acceptance gate — the implementation must turn it green without editing its assertions. Weakening an invariant-shaped assertion (e.g. "lesson still reachable as active" loosened to tolerate `stale`) would pass CI while shipping the underlying bug.
**Why:** regression tests in this repo encode the bug report as an executable spec; editing them to fit the implementation defeats their purpose as a gate.
