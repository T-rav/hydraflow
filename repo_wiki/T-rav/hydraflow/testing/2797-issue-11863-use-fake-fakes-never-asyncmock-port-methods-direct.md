---
id: 2797
topic: testing
source_issue: 11863
source_phase: plan
created_at: 2026-09-01T06:14:33.638567+00:00
status: active
corroborations: 1
---

# Use Fake* fakes; never AsyncMock Port methods directly

MockWorld scenario tests under `tests/scenarios/test_charter_demo_scenarios.py` must run against `FakeGitHub`, `FakeLLM`, and `FakeWorkspace`. Avoid raw `AsyncMock` over Port methods such as `create_issue`.

**Why:** `AsyncMock` stubs shape, not behavior; scripted fake surfaces are required for `CharterLoopRunner` to dispatch deterministically and for refusals to actually be receipted.
