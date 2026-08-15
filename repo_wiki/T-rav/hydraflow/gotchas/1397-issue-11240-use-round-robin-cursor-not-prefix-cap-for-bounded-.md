---
id: 1397
topic: gotchas
source_issue: 11240
source_phase: plan
created_at: 2026-08-15T09:55:52.986956+00:00
status: active
corroborations: 1
---

# Use round-robin cursor, not prefix cap, for bounded open-link passes

When bounding `_diagnose_open_links` by `escape_ledger_max_diagnoses_per_tick`, rotate through `open_links()` circularly via an in-memory `self._diagnose_cursor` index — never a naive prefix cap.
- A prefix cap lets a permanently-INCONCLUSIVE head occupy the first N slots forever; the tail never retires.
- The cursor is an index into a list whose length shifts as links open/close — approximate fairness, not strict permutation. Restart resets to 0 (fail-safe).

**Why:** Without rotation, any cap reintroduces the exact starvation that #11161 fixed for surfaces past position N.
