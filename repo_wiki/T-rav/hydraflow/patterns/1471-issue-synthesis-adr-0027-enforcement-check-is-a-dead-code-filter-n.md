---
id: 1471
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:30:39.034539+00:00
status: active
corroborations: 1
supersedes: 1097
---

# ADR-0027 enforcement check is a dead-code filter, not an allow-list

Describe the ADR-0027 duplicate-model-class enforcement check as a semantic dead-code filter, never as a "curated allow-list."

Example: The 6 exempted classes pass because they are genuinely dead — there is no allow-list mechanism to add to.

**Why:** Mislabeling invites contributors to request exemptions instead of removing dead code, defeating the enforcement ratchet.
