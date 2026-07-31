---
id: 0137
topic: dependencies
source_issue: 10918
source_phase: plan
created_at: 2026-07-31T15:55:12.930295+00:00
status: superseded
corroborations: 1
superseded_by: 0148
---

# Baseline YAML drives p-chart limits; golden-window mean is centerline

Store golden-window baselines as versioned YAML; its mean is the p-chart centerline, and 3-sigma limits widen as per-month ADR count shrinks.

- `setpoint/baselines/hedge.yaml` names its reference window
- `audit/governance.py:upper_control_limit` computes the UCL
- Report the golden-window mean before trusting any live hedge-rate number

**Why:** A taste-tuned hedge lexicon has no natural zero; without the baseline mean, live rates are uninterpretable.
