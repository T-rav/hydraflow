---
id: 1418
topic: gotchas
source_issue: 11286
source_phase: plan
created_at: 2026-08-16T01:54:47.585404+00:00
status: active
corroborations: 1
---

# Finding.fixable: use __post_init__, not field(init=False)

Rule: In `scripts/hydraflow_audit/models.py`, computed fields on `Finding` must stay init-able — compute in `__post_init__`, never `field(init=False)`.

Example: `Finding.fixable` is recomputed in `__post_init__` from `check_id` against `MECHANICALLY_FIXABLE_CHECK_IDS`. The regression pin passes `fixable` as a kwarg; `field(init=False)` would `TypeError`.

**Why:** Tests and callers pass computed fields as kwargs; `init=False` breaks them at construction time.
