---
id: 2791
topic: testing
source_issue: 11862
source_phase: plan
created_at: 2026-09-01T03:40:49.615559+00:00
status: active
corroborations: 1
---

# Split world-reading from pure facts/decisions per ADR-0143 Ruling 5 in src/policy

The policy seam separates three concerns: world-reading functions (`load_charter`, `observe_repo`) that touch the filesystem, pure fact collectors (`collect_charter_facts(charter, observed, *, observed_at)`) that are pure over their inputs, and engine arms (`_decide_charter`) that consume facts and emit verdicts. `Charter`/`ObservedRepo` types are imported under `TYPE_CHECKING` only in `facts.py`.

The caretaker's filing path stays byte-identical; `tests/scenarios/test_charter_drift_caretaker_scenario.py` must stay green unmodified as the proof.

**Why:** Mixing filesystem reads into the engine makes decisions non-replayable from a persisted fact ledger and breaks the round-trip parity guarantee.
