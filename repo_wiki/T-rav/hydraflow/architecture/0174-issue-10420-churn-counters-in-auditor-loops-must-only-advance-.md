---
id: 0174
topic: architecture
source_issue: 10420
source_phase: plan
created_at: 2026-07-24T06:29:23.521341+00:00
status: active
corroborations: 1
---

# Churn counters in auditor loops must only advance in forward scan, never reconcile

In `src/adr_touchpoint_auditor_loop.py`, `bump_shared_infra_churn(paths)` should only be called during the tick's forward scan of merged PRs, not during the reconcile path — reconcile should recompute drift using the already-derived `shared_infra` set without re-bumping churn.

**Why:** a tick that fails before advancing its cursor will re-scan the same PRs; if reconcile also bumped churn, counts would double or triple, prematurely crossing `min_churn` and suppressing drift for modules that aren't actually high-churn.
