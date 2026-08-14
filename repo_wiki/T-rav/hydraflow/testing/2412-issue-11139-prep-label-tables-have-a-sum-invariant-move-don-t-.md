---
id: 2412
topic: testing
source_issue: 11139
source_phase: plan
created_at: 2026-08-14T14:16:51.498098+00:00
status: active
corroborations: 1
---

# Prep label tables have a sum invariant — move, don't copy

When migrating a label between `HYDRAFLOW_LABELS` (config-backed) and `HYDRAFLOW_LITERAL_LABELS` in `src/prep.py`, it must appear in exactly one table. `tests/test_pr_manager_core.py` asserts `len(HYDRAFLOW_LABELS) + len(HYDRAFLOW_LITERAL_LABELS)` total `ensure_labels` create calls.

**Why:** Copying a label into both tables triggers a double-create assertion failure; dropping it makes the label vanish on fresh repos.
