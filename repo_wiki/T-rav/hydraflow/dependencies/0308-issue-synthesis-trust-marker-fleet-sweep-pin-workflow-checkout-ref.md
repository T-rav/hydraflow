---
id: 0308
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-21T11:38:32.623035+00:00
status: active
corroborations: 1
supersedes: 0291
---

# TRUST: marker + fleet sweep pin workflow checkout-ref trust

Any `actions/checkout` ref that is not a literal branch or a `github.*` event-context ref must be preceded by a comment line starting `# TRUST:` explaining why it is trusted.

Example: `tests/architecture/test_staging_rc_dryrun_workflow_shape.py` sweeps every `.github/workflows/*.yml` job containing cache-capable steps and requires each checkout ref to be literal, event-context, or `# TRUST:`-marked. The marker sits immediately above the checkout step.

**Why:** The sweep needs a machine-checkable justification anchor so justified exceptions and unreviewed poisonable steps stay distinguishable as new workflows land.
