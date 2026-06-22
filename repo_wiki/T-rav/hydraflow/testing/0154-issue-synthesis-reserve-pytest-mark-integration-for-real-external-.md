---
id: 0154
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.574648+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Reserve @pytest.mark.integration for real external dependencies only

Mark a test `@pytest.mark.integration` only when it exercises Docker, network, filesystem, real worktrees, or live service instances — not when all deps are `AsyncMock` or `MagicMock`. Use `pytest.mark.skipif(not shutil.which('cli'), ...)` for optional CLI tools.

**Why:** Over-marking slows the fast suite and blurs the unit/integration boundary, making targeted test runs unreliable.
