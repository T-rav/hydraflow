---
id: 1475
topic: gotchas
source_issue: 11412
source_phase: plan
created_at: 2026-08-18T02:58:42.910237+00:00
status: active
corroborations: 1
---

# infra_failure flag is the park-vs-HITL switch

When a diagnosis fallback sets `infra_failure=True`, `DiagnosticLoop._check_diagnosis_gates` (`src/diagnostic_loop.py:291`) parks the loop with a cooldown and returns `"retry"`. When the flag is `False` (the default), the gate walks past its park and escalates to HITL. The flag is the only coupling between classification and loop behavior.

**Why:** Forgetting to set the flag on a new fallback silently routes a failover-lane failure to human paging instead of cooldown retry.
