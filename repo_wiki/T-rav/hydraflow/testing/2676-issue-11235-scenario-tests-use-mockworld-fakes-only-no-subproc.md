---
id: 2676
topic: testing
source_issue: 11235
source_phase: plan
created_at: 2026-08-16T05:30:59.489443+00:00
status: active
corroborations: 1
---

# Scenario tests use MockWorld fakes only — no subprocess/gh/git

`tests/scenarios/test_multi_repo_backend_routing.py` verifies multi-repo provider routing using MockWorld fakes only — no subprocess, `gh`, or `git` calls. When adding scenario tests for routing, stay within MockWorld.

**Why:** Routing logic is pure config resolution; subprocess/gh/git would make tests flaky and slow without adding coverage.
