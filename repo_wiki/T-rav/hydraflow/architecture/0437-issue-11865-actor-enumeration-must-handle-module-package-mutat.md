---
id: 0437
topic: architecture
source_issue: 11865
source_phase: plan
created_at: 2026-09-01T05:42:59.837531+00:00
status: active
corroborations: 1
---

# Actor enumeration must handle module→package mutation (#11669)

In `observe_repo` (`charter_drift_caretaker_loop.py`), the actor-enumeration predicate must resolve both `agents/<name>.md` and `agents/<name>/README.md` as the same actor. Exclude `agents/council/README.md` — it is not an actor.

- An actor moved from `agents/x.md` to `agents/x/README.md` stays enumerated
- Never hardcode an actor list mirroring `agents/`; enumerate at runtime

**Why:** If the predicate only checks flat files, a refactor that nests an actor in a package directory silently drops it from the observed set, masking `loop-without-actor` drift.
