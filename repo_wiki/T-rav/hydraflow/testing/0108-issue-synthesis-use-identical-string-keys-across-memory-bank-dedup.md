---
id: 0108
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.083815+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Use identical string keys across memory bank deduplication and assembly

The `bank_order` list and bank dict keys must use identical strings throughout (e.g., `'review_insights'` everywhere, never mixed with `'review-insights'`). Fallback recall functions should try multiple field names (`learning`, `text`, `content`, `display_text`) to extract the text payload.

**Why:** Key mismatches silently skip entire banks during deduplication or assembly with no error or warning.
