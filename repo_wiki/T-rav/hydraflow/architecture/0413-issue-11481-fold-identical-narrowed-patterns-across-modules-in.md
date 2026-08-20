---
id: 0413
topic: architecture
source_issue: 11481
source_phase: plan
created_at: 2026-08-20T09:13:45.273118+00:00
status: active
corroborations: 1
---

# Fold identical narrowed patterns across modules into a class regression

When an identical narrowed regex sits at multiple sites (e.g., `src/branch_gc_scan.py` and `src/pr_manager.py`), treat it as a single class defect. Write one class regression test modeled after `tests/regressions/test_agent_branch_pattern_class_11281.py`.

**Why:** Ensures all variations are fixed atomically and prevents future divergence across loop engines like `StaleIssueLoop` and `LabelDriftWatcherLoop`.
