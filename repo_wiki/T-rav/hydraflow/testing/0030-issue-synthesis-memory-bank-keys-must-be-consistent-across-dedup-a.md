---
id: 0030
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.411216+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Memory bank keys must be consistent across dedup and assembly

Use identical string keys (`"review_insights"`, not `"review-insights"`) in both deduplication priority maps and bank-assembly pipelines.

Fallback recall functions must try multiple field names (`learning`, `text`, `content`, `display_text`) when extracting text payload from different bank record formats.

**Why:** Mismatched keys cause entire banks to be silently skipped during validation, producing gaps that look like passing coverage.
