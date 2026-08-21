---
id: 0422
topic: architecture
source_issue: 11518
source_phase: review
created_at: 2026-08-21T12:23:02.881244+00:00
status: active
corroborations: 1
---

# Fleet sweep must test both new-shape prevention AND existing offenders

Design fleet sweeps to detect both new instances of a prevented pattern AND existing instances already in the fleet, not just synthetic cases.

Example: The cache-writing classifier in `test_staging_rc_dryrun_workflow_shape.py` tests future shapes; it should also verify that `.github/workflows/quality.yml:168` (pre-existing setup-go cache) is correctly detected.

**Why:** Classifiers tested only against synthetic cases can silently miss variations of the pattern in actual fleet workflows, defeating the sweep's prevention goal.
