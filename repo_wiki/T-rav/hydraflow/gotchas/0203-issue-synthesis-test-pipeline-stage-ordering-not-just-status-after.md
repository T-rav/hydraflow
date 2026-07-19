---
id: 0203
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.158378+00:00
status: active
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
---

# Test pipeline stage ordering, not just status, after inserting stage

After inserting a new stage into `PIPELINE_STAGES`, assert both that the stage's status value is correct and that its array index is correct.

Example: inserting a stage at index 2 shifts all downstream indices; a test checking only `status == 'active'` passes while skip-detection silently breaks.

**Why:** Index-based progression logic produces incorrect skip decisions when stages are reordered, with no immediate test failure.
