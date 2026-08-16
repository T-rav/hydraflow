---
id: 2723
topic: testing
source_issue: 11352
source_phase: plan
created_at: 2026-08-16T14:31:03.716413+00:00
status: active
corroborations: 1
---

# Reuse fake-timer + MockWS + fetch-spy harness for cadence assertions

`context/__tests__/HydraFlowContext.test.jsx` already has a `vi.useFakeTimers()` + MockWS + `fetch`-spy harness that counts `/api/pipeline` calls to prove poll cadence (see the "F10: pipeline REST poll fires at the 30s safety-net cadence" test). Reuse it for any new time-based re-poll or tripwire assertion.

- Positive staleness trips stay at this layer — reproducing a 90s stall in a real browser costs wall-clock time.
- Browser e2e (`tests/scenarios/browser/scenarios/test_realtime_browser.py`) only adds cheap negative cases.

**Why:** Browser e2e for time-based staleness is prohibitively slow; the fake-timer harness proves the same behavior deterministically.
