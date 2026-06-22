---
id: 0094
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.080208+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Reserve @pytest.mark.integration for real external dependencies only

Mark a test `@pytest.mark.integration` only when it exercises Docker, network, filesystem, real worktrees, or live service instances — not when all deps are `AsyncMock` or `MagicMock`. Use `pytest.mark.skipif(not shutil.which('cli'), ...)` for optional CLI tools.

**Why:** Over-marking slows the fast suite and blurs the unit/integration boundary, making targeted test runs unreliable.
