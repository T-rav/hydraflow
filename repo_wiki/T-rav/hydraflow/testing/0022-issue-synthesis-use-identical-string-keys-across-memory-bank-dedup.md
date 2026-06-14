---
id: 0022
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.829807+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Use identical string keys across memory bank deduplication and assembly

The `bank_order` list and bank dict keys must use identical strings throughout (e.g., `"review_insights"` everywhere, never a mix of `"review_insights"` and `"review-insights"`).

Fallback recall functions should try multiple field names (`learning`, `text`, `content`, `display_text`) to extract the text payload.

**Why:** Key mismatches silently skip entire banks during deduplication or assembly with no error or warning.
