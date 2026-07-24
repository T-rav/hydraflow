---
id: 0593
topic: gotchas
source_issue: 10433
source_phase: review
created_at: 2026-07-24T12:05:49.923017+00:00
status: active
corroborations: 1
---

# Don't bundle unrelated wiki wording edits into ADR-drift fix commits

Keep ADR-citation/drift fix commits scoped to the citation change only — wording tweaks to `docs/wiki/dark-factory.md` or `docs/wiki/gotchas.md` bundled into the same commit as an ADR-0019 citation fix were flagged as scope creep in review, even though the core fix was correct.

**Why:** Mixing unrelated wiki prose edits into a targeted drift fix muddies the diff for reviewers and makes it harder to isolate the P2 regression-test gap from cosmetic changes.
