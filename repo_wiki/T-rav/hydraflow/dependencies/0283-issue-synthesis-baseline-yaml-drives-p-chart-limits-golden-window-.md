---
id: 0283
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-18T13:47:37.726298+00:00
status: active
corroborations: 1
supersedes: 0265
---

# Baseline YAML drives p-chart limits; golden-window mean is centerline

Store golden-window baselines as versioned YAML; its mean is the p-chart centerline, and 3-sigma limits widen as per-month ADR count shrinks.

Example: `setpoint/baselines/hedge.yaml` names its reference window; `audit/governance.py:upper_control_limit` computes the UCL; report the golden-window mean before trusting any live hedge-rate number.

**Why:** A taste-tuned hedge lexicon has no natural zero; without the baseline mean, live rates are uninterpretable.
