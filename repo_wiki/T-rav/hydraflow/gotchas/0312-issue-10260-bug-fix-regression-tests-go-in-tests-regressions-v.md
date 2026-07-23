---
id: 0312
topic: gotchas
source_issue: 10260
source_phase: review
created_at: 2026-07-22T11:54:54.586699+00:00
status: superseded
corroborations: 1
superseded_by: 0317
---

# Bug-fix regression tests go in tests/regressions/ via LoopDeps + Fake* adapters

Follow the established pattern for new regression coverage: direct loop instantiation using `LoopDeps` wired to `Fake*` adapters (e.g. `FakeGithub`), placed under `tests/regressions/`, matching prior precedent like `regression_issue_10225.py` — not a separate `tests/scenarios/` file unless the bug is loop-integration-shaped.

**Why:** Keeps regression coverage lightweight and consistent so reviewers recognize the pattern immediately instead of re-deriving test scaffolding per fix.
