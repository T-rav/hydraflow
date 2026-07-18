---
id: 0101
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:10:32.487234+00:00
status: active
corroborations: 1
supersedes: 0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077
---

# Test pipeline stage ordering, not just status, after inserting stage

After inserting a new stage into `PIPELINE_STAGES`, assert both that the stage's status value and its array index are correct.

Example: inserting a stage at index 2 shifts all downstream indices; a test checking only `status == 'active'` passes while skip-detection silently breaks.

**Why:** Index-based progression logic produces incorrect skip decisions when stages are reordered, with no immediate test failure.
