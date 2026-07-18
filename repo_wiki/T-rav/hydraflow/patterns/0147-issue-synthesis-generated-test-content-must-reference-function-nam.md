---
id: 0147
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.024683+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Generated test content must reference function names, not line numbers

Test skeletons, comments, and generated assertions must use exact function/class names for stability across refactors.

Example: `# tests path through calculate_drift()` not `# tests line 42 in drift.py`.

**Why:** Line numbers shift on every edit, making generated references immediately stale and misleading.
