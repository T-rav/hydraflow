---
id: 0276
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:48:26.490132+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Memory bank keys must be consistent across dedup and assembly

Use identical string keys (`'review_insights'`, not `'review-insights'`) in both deduplication priority maps and bank-assembly pipelines.

Fallback recall functions must try multiple field names (`learning`, `text`, `content`, `display_text`) when extracting text payload from different bank record formats.

**Why:** Mismatched keys cause entire banks to be silently skipped during validation, producing gaps that look like passing coverage.
