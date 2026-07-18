---
id: 0296
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.876904+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Mark @pytest.mark.integration only for real external deps

Apply `@pytest.mark.integration` only when a test exercises Docker, network, filesystem, real worktrees, or live service instances — not when all deps are `AsyncMock` or `MagicMock`.

- Use `pytest.mark.skipif(shutil.which("tool") is None, ...)` for optional CLI tools.

**Why:** Over-marking slows the fast suite and blurs the unit/integration boundary, making targeted test runs unreliable.
