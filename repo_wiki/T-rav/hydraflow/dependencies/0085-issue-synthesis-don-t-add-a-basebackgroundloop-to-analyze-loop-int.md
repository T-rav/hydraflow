---
id: 0085
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:21:57.759657+00:00
status: superseded
corroborations: 1
supersedes: 0077
superseded_by: 0093
---

# Don't add a BaseBackgroundLoop to analyze loop interactions

Use a one-shot script, not a `BaseBackgroundLoop` subclass, for loop-interaction analysis tools.

Example:
- `scripts/interaction_report.py` runs the analysis without registering a controller.
- No loop means no ADR-0049 kill-switch is required.
- The `src/interaction/` package has no runner, no store, no registration.

**Why:** Adding a 71st controller to measure 70 loops is the pathology under study — the tool becomes its own confound.
