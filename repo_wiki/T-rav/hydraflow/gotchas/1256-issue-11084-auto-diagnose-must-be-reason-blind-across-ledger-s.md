---
id: 1256
topic: gotchas
source_issue: 11084
source_phase: plan
created_at: 2026-08-14T05:53:19.138389+00:00
status: active
corroborations: 1
---

# Auto-diagnose must be reason-blind across ledger surfaces

Pass every eligible surface through `_auto_diagnose` in `escape_ledger_loop.py` regardless of reason. The aging surface's answered-predicate is `encoded_as != "none-yet"` (`:234`) — exactly the field a `RESOLVED_ENCODED` verdict writes — so gating on `low-confidence` alone leaves the one surface asking for an encoding unanswered.
- Bug: the gate passed everything *except* `low-confidence` (backwards).
- Fix: drop the reason-equality gate; INCONCLUSIVE must still page a human.
**Why:** A reason gate excluding the surface whose answered-field the verdict writes produces silent self-answerable HITL issues (see #11084).
