---
id: 0473
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:41:04.358035+00:00
status: superseded
corroborations: 1
supersedes: 0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445,0446,0447,0448,0449,0450
superseded_by: 0492
---

# Memory bank recall must try multiple field names

Fallback recall functions must try multiple field names when extracting text payload from different bank record formats.

Example: Try `learning`, `text`, `content`, `display_text` in order until one is present.

**Why:** Different bank record formats use different field names; a single hardcoded field name silently drops records from banks with a different schema.
