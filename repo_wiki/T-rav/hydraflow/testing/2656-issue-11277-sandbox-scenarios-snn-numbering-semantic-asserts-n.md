---
id: 2656
topic: testing
source_issue: 11277
source_phase: plan
created_at: 2026-08-15T21:08:01.026782+00:00
status: active
corroborations: 1
---

# Sandbox scenarios: sNN numbering, semantic asserts, no skip

Sandbox e2e scenarios in `tests/sandbox_scenarios/scenarios/` use the next free `sNN` prefix (s90 was last at time of writing — check for parallel claims). Each scenario follows `seed()`/`assert_outcome(api, page)` shape, is auto-discovered by the runner, and must use semantic DOM asserts (`data-testid`) backed by FakeGitHub's `api.wait_until`. Never use `pytest.skip`; if a scenario can't be fully expressed, assert what's possible and file a follow-up.
**Why:** Skipping or weakening assertions defeats the e2e purpose; the runner treats skips as green.
