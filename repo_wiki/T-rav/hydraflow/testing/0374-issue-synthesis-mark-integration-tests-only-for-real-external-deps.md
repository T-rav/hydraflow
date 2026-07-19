---
id: 0374
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:49:52.717454+00:00
status: superseded
corroborations: 1
supersedes: 0334,0335,0336,0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347,0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369,0370,0371,0372
superseded_by: 0412
---

# Mark integration tests only for real external deps

Apply `@pytest.mark.integration` only when a test exercises Docker, network, filesystem, real worktrees, or live services — not when all deps are mocked.

Example: Use `pytest.mark.skipif(shutil.which("tool") is None, ...)` for optional CLI tools instead of marking as integration.

**Why:** Over-marking slows the fast suite and blurs the unit/integration boundary, making targeted test runs unreliable.
