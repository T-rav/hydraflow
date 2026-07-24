---
id: 0181
topic: architecture
source_issue: 10437
source_phase: plan
created_at: 2026-07-24T10:30:36.222713+00:00
status: active
corroborations: 1
---

# ADR-drift rollup issues auto-close via _reconcile_stale_rollups

After fixing an ADR-drift false positive (e.g. via `_SHARED_INFRA_MODULES`), don't manually close the filed rollup issue. `_reconcile_stale_rollups` recomputes drift over the originating PR's own diff on the next ADR-drift auditor tick and auto-closes the issue once drift is empty — this closed #10437 (ADR-0106 FP from PR #10414) without manual intervention, and would also auto-close a sibling ADR-0055 rollup on the same file in the same tick.

**Why:** Avoids wasted manual triage — a correct source fix is sufficient; the auditor reconciles rollup issues itself.
