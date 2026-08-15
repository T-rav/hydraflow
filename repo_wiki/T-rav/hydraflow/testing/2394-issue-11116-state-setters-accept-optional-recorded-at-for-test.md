---
id: 2394
topic: testing
source_issue: 11116
source_phase: plan
created_at: 2026-08-14T10:10:56.158191+00:00
status: superseded
corroborations: 1
superseded_by: 2582
---

# State setters accept optional recorded_at for test determinism

`set_prompt_efficiency_baseline(snapshot, *, recorded_at: str | None = None)` — production omits the arg and the setter stamps UTC ISO; tests pass an explicit string. Apply this to any state setter that stamps time.

**Why:** Auto-stamped `datetime.now()` makes persisted-state assertions non-deterministic across cap-trim and round-trip tests in `tests/test_state_tracking.py`.
