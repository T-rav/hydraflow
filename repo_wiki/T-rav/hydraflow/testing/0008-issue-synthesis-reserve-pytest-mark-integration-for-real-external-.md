---
id: 0008
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.827243+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Reserve @pytest.mark.integration for real external dependencies only

Mark a test `@pytest.mark.integration` only when it exercises Docker, network, filesystem, real worktrees, or live service instances — not when all deps are `AsyncMock` or `MagicMock`.

Use `pytest.mark.skipif(not shutil.which("cli"), ...)` for optional CLI tools.

**Why:** Over-marking slows the fast suite and blurs the boundary between unit and integration layers, making targeted test runs unreliable.
