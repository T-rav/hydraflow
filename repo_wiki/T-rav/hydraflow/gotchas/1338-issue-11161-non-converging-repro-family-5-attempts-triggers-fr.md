---
id: 1338
topic: gotchas
source_issue: 11161
source_phase: review
created_at: 2026-08-14T20:59:54.755919+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Non-converging repro family (5+ attempts) triggers fresh-eyes pass

When a repro family has failed to converge five or more times (#11126, #11128, #11144, #11160, #11161), the pre-flight plan's escalation signal applies: two or more real findings from focus areas warrant a second fresh-eyes pass rather than proceeding to merge.

- Track sibling issues in the family — repeated failures on the same escape indicate a structural misunderstanding, not a missing tweak.
- Use the fresh-eyes pass to re-examine ordering and lifecycle assumptions (e.g. fingerprint exclusion vs. diagnosis) before another fix attempt.

**Why:** Iterating on the same incorrect mental model wastes review cycles; a fresh pass breaks the loop.
