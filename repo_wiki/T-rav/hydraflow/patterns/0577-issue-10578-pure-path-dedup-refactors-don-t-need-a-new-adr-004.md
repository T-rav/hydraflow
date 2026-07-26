---
id: 0577
topic: patterns
source_issue: 10578
source_phase: plan
created_at: 2026-07-26T01:20:17.466881+00:00
status: active
corroborations: 1
---

# Pure path-dedup refactors don't need a new ADR-0049 kill-switch

A refactor that only collapses duplicate path-resolution logic (no new loop, no new subprocess-spawning runner) doesn't trigger ADR-0049's kill-switch requirement. Instead, pin that the existing switches still gate the touched loops: `HYDRAFLOW_ESCAPE_LEDGER_LOOP_ENABLED` and `HYDRAFLOW_SAMPLED_AUDIT_LOOP_ENABLED` in `src/config.py`, verified via regression test that both loops report disabled and skip touching the ledger path when unset.
**Why:** avoids over-applying the kill-switch rule to changes that carry zero new runtime behavior.
