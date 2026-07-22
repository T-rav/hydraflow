---
id: 0344
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T04:08:36.284956+00:00
status: superseded
corroborations: 1
supersedes: 0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333,0334,0335,0336,0337,0338,0339,0340,0341,0342,0343
superseded_by: 0350
---

# Reference function names, not line numbers, in generated tests

Test skeletons, comments, and generated assertions must use exact function/class names for stability across refactors.

Example: `# tests path through calculate_drift()` not `# tests line 42 in drift.py`.

**Why:** Line numbers shift on every edit, making generated references immediately stale and misleading.
