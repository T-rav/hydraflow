---
id: 0436
topic: architecture
source_issue: 11865
source_phase: plan
created_at: 2026-09-01T05:42:59.837516+00:00
status: active
corroborations: 1
---

# ADR-0143 Ruling 5: actor enumeration is filesystem, decide stays pure

Actor enumeration happens in `observe_repo` (in `charter_drift_caretaker_loop.py`) and arrives at `compute_charter_drift` (in `charter.py`) as an `ObservedRepo.present_actors` field. Never reach into the filesystem from `compute_charter_drift`.

- The observed-actor set is `frozenset[str] | None` on `ObservedRepo`
- Putting filesystem calls inside `compute_charter_drift` breaks `test_policy_engine_is_pure.py` and the Ruling 5 seam

**Why:** The seam keeps the decide half pure and testable without a repo on disk; mixing observation into decision couples the pure layer to I/O and breaks the policy-engine purity gate.
