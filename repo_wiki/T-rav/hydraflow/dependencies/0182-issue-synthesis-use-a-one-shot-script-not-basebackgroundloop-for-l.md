---
id: 0182
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T07:06:05.819405+00:00
status: superseded
corroborations: 1
supersedes: 0170
superseded_by: 0197
---

# Use a one-shot script, not BaseBackgroundLoop, for loop analysis

Use a one-shot script, not a `BaseBackgroundLoop` subclass, for loop-interaction analysis tools.

Example: `scripts/interaction_report.py` runs the analysis without registering a controller; no loop means no ADR-0049 kill-switch is required; the `src/interaction/` package has no runner, no store, no registration.

**Why:** Adding a 71st controller to measure 70 loops is the pathology under study — the tool becomes its own confound.
