---
id: 0315
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.889491+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Memory bank keys must be consistent across dedup and assembly

Use identical string keys (`'review_insights'`, not `'review-insights'`) in both deduplication priority maps and bank-assembly pipelines.

- Fallback recall functions must try multiple field names (`learning`, `text`, `content`, `display_text`) when extracting text payload from different bank record formats.

**Why:** Mismatched keys cause entire banks to be silently skipped during validation, producing gaps that look like passing coverage.
