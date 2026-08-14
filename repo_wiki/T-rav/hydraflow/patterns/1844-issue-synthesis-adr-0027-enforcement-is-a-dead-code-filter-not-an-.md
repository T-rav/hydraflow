---
id: 1844
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T14:29:26.365715+00:00
status: superseded
corroborations: 1
supersedes: 1746
superseded_by: 1952
---

# ADR-0027 enforcement is a dead-code filter, not an allow-list

Describe ADR-0027 duplicate-model-class enforcement as a semantic dead-code filter, never as a "curated allow-list."

Example: The 6 exempted classes pass because they are genuinely dead — there is no allow-list mechanism to add to.

**Why:** Mislabeling invites contributors to request exemptions instead of removing dead code, defeating the enforcement ratchet.
