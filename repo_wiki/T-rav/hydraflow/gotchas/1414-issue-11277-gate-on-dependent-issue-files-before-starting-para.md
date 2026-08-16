---
id: 1414
topic: gotchas
source_issue: 11277
source_phase: plan
created_at: 2026-08-15T21:08:01.026765+00:00
status: active
corroborations: 1
---

# Gate on dependent issue files before starting parallel slices

Before starting work that depends on another issue's deliverables, verify their files exist on the base branch. For #11277, Step 0 checks that #11210's `RepoHealthPanel.jsx`/`railsHealth.js`/`hydraflow_healthcheck/`, #11276's endpoint/adapter, and `fixability.py` all exist. If any are missing, stop and requeue — do not absorb their scope.
**Why:** Absorbing a missing prerequisite's scope silently expands the slice beyond one time window and creates merge conflicts.
