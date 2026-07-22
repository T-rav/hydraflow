---
id: 0472
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:41:04.356222+00:00
status: active
corroborations: 1
supersedes: 0412,0413,0414,0415,0416,0417,0418,0419,0420,0421,0422,0423,0424,0425,0426,0427,0428,0429,0430,0431,0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445,0446,0447,0448,0449,0450
---

# Keep memory bank keys consistent across dedup pipelines

Use identical string keys (e.g. `'review_insights'`, not `'review-insights'`) in both deduplication priority maps and bank-assembly pipelines.

Example: A priority map keyed `'review_insights'` must match the bank-assembly pipeline's key exactly, not a hyphenated variant.

**Why:** Mismatched keys cause entire banks to be silently skipped during validation, producing gaps that look like passing coverage.
