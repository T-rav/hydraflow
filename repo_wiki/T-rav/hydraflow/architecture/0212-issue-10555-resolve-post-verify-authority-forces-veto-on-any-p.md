---
id: 0212
topic: architecture
source_issue: 10555
source_phase: plan
created_at: 2026-07-25T22:52:11.067264+00:00
status: active
corroborations: 1
---

# `resolve_post_verify_authority` forces `veto` on any PR touching `review_phase.py`-family files

PRs that modify `src/review_phase/_phase.py` or sibling review-phase modules trigger the self-modification guard, forcing the post-verify authority to `veto` — expect the advisor to be strict on its own review when a change lands in this path.

**Why:** explains otherwise-surprising advisor strictness on review-pipeline PRs; don't read it as a bug in the advisor.
