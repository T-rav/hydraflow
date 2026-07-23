---
id: 0067
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.339051+00:00
status: superseded
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
superseded_by: 0078
---

# Test pipeline stage ordering, not just status, after inserting stage

After inserting a new stage into `PIPELINE_STAGES`, assert both that the stage's status value is correct and that its array index is correct.

Example: inserting a stage at index 2 shifts all downstream indices; a test checking only `status == 'active'` passes while skip-detection silently breaks.

**Why:** Index-based progression logic produces incorrect skip decisions when stages are reordered, with no immediate test failure.
