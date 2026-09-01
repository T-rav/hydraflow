---
id: 1549
topic: gotchas
source_issue: 11863
source_phase: plan
created_at: 2026-09-01T06:14:33.638603+00:00
status: active
corroborations: 1
---

# Probe broker seams first; scenario tests hang on scripted LLM gaps

Before writing a scenario that exercises a loop runner, probe the broker seam the runner dispatches through. For `CharterLoopRunner`, the broker that `FakeLLM` cannot script causes non-deterministic ticks; `tests/sandbox_scenarios/scenarios/s96_charter_demo_e2e.py` then hangs in CI.

**Why:** Scenario e2e blocking on an unprobed seam wastes CI time and produces flaky hangs rather than clean failures.
