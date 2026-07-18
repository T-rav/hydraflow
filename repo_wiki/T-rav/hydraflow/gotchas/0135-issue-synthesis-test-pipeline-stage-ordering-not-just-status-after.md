---
id: 0135
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.604760+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Test pipeline stage ordering, not just status, after inserting stage

After inserting a new stage into `PIPELINE_STAGES`, assert both that the stage's status value is correct and that its array index is correct.

Example: inserting a stage at index 2 shifts all downstream indices; a test checking only `status == 'active'` passes while skip-detection silently breaks.

**Why:** Index-based progression logic produces incorrect skip decisions when stages are reordered, with no immediate test failure.
