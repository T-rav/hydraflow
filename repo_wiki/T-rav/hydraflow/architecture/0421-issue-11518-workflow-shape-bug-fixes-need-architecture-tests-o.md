---
id: 0421
topic: architecture
source_issue: 11518
source_phase: review
created_at: 2026-08-21T12:23:02.881237+00:00
status: active
corroborations: 1
---

# Workflow-shape bug fixes need architecture tests only

For bug fixes in workflow structure or CI shape (e.g., cache-poisoning alerts triggered by job configuration), add architecture tests only — MockWorld scenario and sandbox e2e layers are N/A per `docs/standards/testing/README.md`.

Example: PR #11560 adds `tests/architecture/test_staging_rc_dryrun_workflow_shape.py` for cache-poisoning prevention, with no MockWorld or sandbox layers.

**Why:** Workflow-shape bugs are not observable through loop/runner paths; runtime test layers cannot mutate or verify workflow YAML structure.
