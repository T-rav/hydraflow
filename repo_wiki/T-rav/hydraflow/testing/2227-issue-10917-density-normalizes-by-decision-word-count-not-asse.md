---
id: 2227
topic: testing
source_issue: 10917
source_phase: plan
created_at: 2026-07-31T16:16:35.877453+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Density normalizes by Decision word count, not assertions

Normalize checkable-assertion density by Decision-section word count, never by MUST/SHALL sentence count. In `docs/adr`, 32 of 78 Accepted ADRs have zero MUST/SHALL sentences, so an assertion denominator is undefined for them. A zero-word Decision section must report `unnormalizable`, not raise divide-by-zero. **Why:** Picking assertion count was the stall that blocked #10829's implement phase; word count is settled on measured evidence — file a follow-up rather than re-litigating.
