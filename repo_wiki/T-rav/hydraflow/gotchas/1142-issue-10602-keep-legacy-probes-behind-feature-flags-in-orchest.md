---
id: 1142
topic: gotchas
source_issue: 10602
source_phase: plan
created_at: 2026-07-26T10:26:40.201281+00:00
status: superseded
corroborations: 1
superseded_by: 1144
---

# Keep legacy probes behind feature flags in orchestrator

When replacing `probe_credit_availability` in `src/orchestrator.py`, keep the legacy path behind a feature flag (`credit_canary_enabled=False`) instead of deleting it. Deleting it breaks the kill-switch path and unrelated suites (PR #8460 lesson). **Why:** Ensures a real revert path exists and prevents test breakage if the new detection mechanism fails.
