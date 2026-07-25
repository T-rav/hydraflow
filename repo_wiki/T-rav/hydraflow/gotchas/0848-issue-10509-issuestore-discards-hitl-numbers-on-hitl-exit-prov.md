---
id: 0848
topic: gotchas
source_issue: 10509
source_phase: plan
created_at: 2026-07-25T05:02:36.104085+00:00
status: active
corroborations: 1
---

# IssueStore discards _hitl_numbers on HITL exit — provenance needs a separate additive set

`IssueStore` tracks HITL membership with `_hitl_numbers`, but it's removed once an issue exits HITL (`issue_store.py:317/325/416/419`), so "did this issue ever visit HITL" is unrecoverable downstream. To expose history (not just current bucket), add a separate additive set like `_hitl_visited` that's only ever added to, mirroring how `_merged_numbers` already works, and stamp it onto the snapshot entry in `_build_cached_entry`. Record it at every escalation entry point, not just one — label reconciliation (~l.316) and stage advance (~l.418) are two independent paths that can each set it.

**Why:** membership sets that get cleared on exit can't answer historical questions; missing one of the two escalation call sites silently loses provenance for that path.
