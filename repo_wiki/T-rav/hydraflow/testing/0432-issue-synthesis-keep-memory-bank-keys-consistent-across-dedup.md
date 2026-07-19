---
id: 0432
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:46:15.857742+00:00
status: active
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401,0402,0403,0404,0405,0406,0407,0408,0409,0410,0411
---

# Keep memory bank keys consistent across dedup

Use identical string keys (`'review_insights'`, not `'review-insights'`) in both deduplication priority maps and bank-assembly pipelines.

Example: Fallback recall functions must try multiple field names (`learning`, `text`, `content`, `display_text`) when extracting text payload from different bank record formats.

**Why:** Mismatched keys cause entire banks to be silently skipped during validation, producing gaps that look like passing coverage.
