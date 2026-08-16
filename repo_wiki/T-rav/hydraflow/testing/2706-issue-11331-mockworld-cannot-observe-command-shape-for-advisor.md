---
id: 2706
topic: testing
source_issue: 11331
source_phase: plan
created_at: 2026-08-16T09:57:29.108953+00:00
status: active
corroborations: 1
---

# MockWorld cannot observe command shape for advisor/ultra runners

Scenario tests (MockWorld tier) are structurally N/A for asserting command flags on `_build_post_verify_runner` and `_build_ultra_runner`. Both short-circuit into `FakeLLM.pop_advisor_result` before `build_agent_command` runs, so no scenario can observe `--permission-mode` or `--allowedTools`.

- Use direct unit tests on `build_*_command` / `build_agent_command` instead.
- See `tests/test_ultra_review.py::TestBuildCommand` for the precedent shape.

**Why:** Attempting to pin command flags through MockWorld scenarios produces false confidence — the command is never assembled in that code path.
