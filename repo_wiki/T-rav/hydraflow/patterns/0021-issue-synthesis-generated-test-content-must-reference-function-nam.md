---
id: 0021
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.315425+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Generated test content must reference function names, not line numbers

Test skeletons, comments, and generated assertions must use exact function/class names for stability across refactors.

Example: `# tests path through calculate_drift()` not `# tests line 42 in drift.py`.

**Why:** Line numbers shift on every edit, making generated references immediately stale and misleading.
