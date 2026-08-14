---
id: 2582
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.780735+00:00
status: active
corroborations: 1
supersedes: 2394
---

# State setters accept optional recorded_at for test determinism

`set_prompt_efficiency_baseline(snapshot, *, recorded_at: str | None = None)` — production omits the arg and the setter stamps UTC ISO; tests pass an explicit string. Apply this to any state setter that stamps time.

**Why:** Auto-stamped `datetime.now()` makes persisted-state assertions non-deterministic across cap-trim and round-trip tests in `tests/test_state_tracking.py`.
