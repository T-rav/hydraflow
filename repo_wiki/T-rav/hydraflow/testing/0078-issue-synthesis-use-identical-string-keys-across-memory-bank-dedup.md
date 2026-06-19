---
id: 0078
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.273630+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Use identical string keys across memory bank deduplication and assembly

The `bank_order` list and bank dict keys must use identical strings throughout (e.g., `'review_insights'` everywhere, never mixed with `'review-insights'`). Fallback recall functions should try multiple field names (`learning`, `text`, `content`, `display_text`) to extract the text payload.

**Why:** Key mismatches silently skip entire banks during deduplication or assembly with no error or warning.
