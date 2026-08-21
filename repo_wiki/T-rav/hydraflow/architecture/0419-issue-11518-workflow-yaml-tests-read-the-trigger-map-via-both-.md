---
id: 0419
topic: architecture
source_issue: 11518
source_phase: plan
created_at: 2026-08-21T09:08:16.052894+00:00
status: active
corroborations: 1
---

# Workflow YAML tests: read the trigger map via both `on` and `True` keys

When shape-testing `.github/workflows/*.yml` with `yaml.safe_load`, fetch the trigger block through both keys: `wf.get("on") or wf.get(True)`.

- YAML 1.1 coerces the bare key `on` to boolean `True`, so `wf["on"]` can KeyError or silently miss the trigger map.
- Pattern already used at `tests/test_external_security_review_workflow.py:40`; reused by `tests/architecture/test_staging_rc_dryrun_workflow_shape.py`.

**Why:** Trigger-dependent assertions otherwise vacuously pass against the wrong key, leaving the pin green while asserting nothing.
