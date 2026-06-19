---
id: 0138
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.436245+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Use identical string keys across memory bank deduplication and assembly

The `bank_order` list and bank dict keys must use identical strings throughout (e.g., `'review_insights'` everywhere, never mixed with `'review-insights'`). Fallback recall functions should try multiple field names (`learning`, `text`, `content`, `display_text`) to extract the text payload.

**Why:** Key mismatches silently skip entire banks during deduplication or assembly with no error or warning.
