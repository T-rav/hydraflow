---
id: 0237
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:45:05.801267+00:00
status: superseded
corroborations: 1
supersedes: 0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213
superseded_by: 0248
---

# Test pipeline stage ordering, not just status, after inserting stage

After inserting a new stage into `PIPELINE_STAGES`, assert both that the stage's status value is correct and that its array index is correct.

Example: inserting a stage at index 2 shifts all downstream indices; a test checking only `status == 'active'` passes while skip-detection silently breaks.

**Why:** Index-based progression logic produces incorrect skip decisions when stages are reordered, with no immediate test failure.
