---
id: 0168
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.579096+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Use identical string keys across memory bank deduplication and assembly

The `bank_order` list and bank dict keys must use identical strings throughout (e.g., `'review_insights'` everywhere, never mixed with `'review-insights'`). Fallback recall functions should try multiple field names (`learning`, `text`, `content`, `display_text`) to extract the text payload.

**Why:** Key mismatches silently skip entire banks during deduplication or assembly with no error or warning.
