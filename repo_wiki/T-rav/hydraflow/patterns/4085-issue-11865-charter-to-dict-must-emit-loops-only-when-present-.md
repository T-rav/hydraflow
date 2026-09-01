---
id: 4085
topic: patterns
source_issue: 11865
source_phase: plan
created_at: 2026-09-01T05:42:59.837524+00:00
status: active
corroborations: 1
---

# Charter.to_dict must emit loops: only when present, not empty

In `charter_model.py`, `Charter.to_dict` must omit the `loops:` key entirely when `loops` is absent (`None`), and emit `{}` only when explicitly empty. This preserves absent≠empty across a `to_dict`/`load_charter` round-trip.

- Absent `loops` skips binding entirely (no findings)
- Empty `loops: {}` with observed actors produces `actor-without-loop` findings
- `declares_nothing_checkable` counts a present `loops` block as checkable

**Why:** Collapsing absent and empty makes a charter that declares no loops indistinguishable from one that declares zero loops, silently changing drift behavior after a round-trip.
