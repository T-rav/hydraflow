---
id: 0008
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.408369+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Mark @pytest.mark.integration only for real external dependencies

Apply `@pytest.mark.integration` only when a test exercises Docker, network, filesystem, worktrees, or live service instances. Tests that mock all deps with `spec=AsyncMock` are unit/functional tests.

Use `pytest.mark.skipif(shutil.which("tool") is None, ...)` for optional CLI tools.

**Why:** Incorrect markers cause tests to run (or be skipped) in the wrong suite, hiding real coverage gaps.
