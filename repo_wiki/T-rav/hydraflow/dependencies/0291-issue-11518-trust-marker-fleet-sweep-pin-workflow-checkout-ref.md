---
id: 0291
topic: dependencies
source_issue: 11518
source_phase: plan
created_at: 2026-08-21T09:08:16.052874+00:00
status: superseded
corroborations: 1
superseded_by: 0308
---

# # TRUST: marker + fleet sweep pin workflow checkout-ref trust

Any `actions/checkout` ref that is not a literal branch or a `github.*` event-context ref must be preceded by a comment line starting `# TRUST:` explaining why it is trusted.

- `tests/architecture/test_staging_rc_dryrun_workflow_shape.py` sweeps every `.github/workflows/*.yml` job containing cache-capable steps (`pip install`, `docker build`/`compose`, `actions/cache`, `npm/yarn install`) and requires each checkout ref to be literal, event-context, or `# TRUST:`-marked.
- The marker sits immediately above the checkout step; the test scans raw text, not the parsed YAML tree.

**Why:** The sweep needs a machine-checkable justification anchor so justified exceptions and unreviewed poisonable steps stay distinguishable as new workflows land.
