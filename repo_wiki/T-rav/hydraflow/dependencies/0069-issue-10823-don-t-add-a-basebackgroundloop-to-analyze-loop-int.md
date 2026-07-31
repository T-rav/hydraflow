---
id: 0069
topic: dependencies
source_issue: 10823
source_phase: plan
created_at: 2026-07-31T00:48:51.333082+00:00
status: active
corroborations: 1
---

# Don't add a BaseBackgroundLoop to analyze loop interactions

Use a one-shot script, not a `BaseBackgroundLoop` subclass, for loop-interaction analysis tools.

- `scripts/interaction_report.py` runs the analysis without registering a controller.
- No loop means no ADR-0049 kill-switch is required.
- The `src/interaction/` package has no runner, no store, no registration.

**Why:** Adding a 71st controller to measure 70 loops is the pathology under study — the tool becomes its own confound.
