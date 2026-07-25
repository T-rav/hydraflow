---
id: 0827
topic: gotchas
source_issue: 10493
source_phase: plan
created_at: 2026-07-24T23:45:36.554296+00:00
status: active
corroborations: 1
---

# ADR-0005 PR recovery: diff-bearing branches recover, zero-diff still escalates to HITL

Amending `docs/adr/0005-pr-recovery-and-zero-diff-branch-handling.md`: a branch with commits and a real diff from base that fails to open a PR should recover (retry `gh pr create`, adopt an existing PR, or mark pending for re-pick) rather than parking. A branch with zero diff from base still escalates to HITL — there's nothing to salvage. Keep this distinction explicit in `_handle_no_pr_fallback`'s logic in `src/implement_phase.py`.

**Why:** treating all no-PR outcomes identically either strands salvageable pushed work or silently auto-recovers empty branches that need a human's attention.
