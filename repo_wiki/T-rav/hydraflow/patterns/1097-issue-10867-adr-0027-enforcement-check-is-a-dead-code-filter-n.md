---
id: 1097
topic: patterns
source_issue: 10867
source_phase: review
created_at: 2026-07-31T10:45:43.194331+00:00
status: active
corroborations: 1
---

# ADR-0027 enforcement check is a dead-code filter, not an allow-list

Describe the ADR-0027 duplicate-model-class enforcement check as a semantic dead-code filter, never as a "curated allow-list." It flags classes with identical names but distinct definitions as dead duplicates; the 6 existing exempted classes pass because they are genuinely dead, not because someone added them to a list. There is no allow-list mechanism.

**Why:** Mislabeling the mechanism invites contributors to request exemptions instead of removing dead code, defeating the enforcement ratchet.
