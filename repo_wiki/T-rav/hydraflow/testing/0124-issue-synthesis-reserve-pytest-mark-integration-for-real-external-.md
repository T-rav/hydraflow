---
id: 0124
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.432106+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# Reserve @pytest.mark.integration for real external dependencies only

Mark a test `@pytest.mark.integration` only when it exercises Docker, network, filesystem, real worktrees, or live service instances — not when all deps are `AsyncMock` or `MagicMock`. Use `pytest.mark.skipif(not shutil.which('cli'), ...)` for optional CLI tools.

**Why:** Over-marking slows the fast suite and blurs the unit/integration boundary, making targeted test runs unreliable.
