---
id: 0342
topic: architecture
source_issue: 11186
source_phase: plan
created_at: 2026-08-15T00:14:35.607946+00:00
status: active
corroborations: 1
---

# test_regression_rot_scan.py pins ADR test module names

Do not rename `_RIGHT_SIZED`, `expected_symbol_owner`, or the module file `test_issue_9419_9421_adr_drift.py`. `test_regression_rot_scan.py` and the repo-wiki depend on all three. Also, regression guards must read `test_*` attrs off the loaded module — never import `_`-prefixed names cross-module.

**Why:** Renaming breaks rot-scan and wiki linkage silently.
