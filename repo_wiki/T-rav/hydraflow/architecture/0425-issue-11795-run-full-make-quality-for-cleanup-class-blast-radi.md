---
id: 0425
topic: architecture
source_issue: 11795
source_phase: plan
created_at: 2026-08-30T07:41:57.361407+00:00
status: active
corroborations: 1
---

# Run full make quality for cleanup-class blast radius

Run the full `make quality` suite instead of file subsets when modifying cleanup-class code or branch protection audits. Verify changes spanning `test_gates_*.py` or `test_branch_protection_audit.py` against the full suite.

**Why:** File-subset test runs miss unit and scenario layer interactions across the cleanup-class blast radius.
