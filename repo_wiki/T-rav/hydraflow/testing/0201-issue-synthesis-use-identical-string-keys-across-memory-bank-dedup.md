---
id: 0201
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.789055+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Use identical string keys across memory bank deduplication and assembly

The `bank_order` list and bank dict keys must use identical strings throughout (e.g., `'review_insights'` everywhere, never mixed with `'review-insights'`). Fallback recall functions should try multiple field names (`learning`, `text`, `content`, `display_text`) to extract text payloads.

**Why:** Key mismatches silently skip entire banks during deduplication or assembly with no error or warning.
