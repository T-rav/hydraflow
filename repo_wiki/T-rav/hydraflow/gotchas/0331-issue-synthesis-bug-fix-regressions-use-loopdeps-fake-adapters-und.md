---
id: 0331
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T15:33:18.680110+00:00
status: active
corroborations: 1
supersedes: 0317,0318,0319,0320,0321,0322,0323,0324,0325,0326
---

# Bug-fix regressions use LoopDeps + Fake* adapters under tests/regressions/

Follow the established pattern for new regression coverage: direct loop instantiation using `LoopDeps` wired to `Fake*` adapters (e.g. `FakeGithub`), placed under `tests/regressions/` — not a separate `tests/scenarios/` file unless the bug is loop-integration-shaped.

Example: matches prior precedent like `regression_issue_10225.py`.

**Why:** Keeps regression coverage lightweight and consistent so reviewers recognize the pattern immediately instead of re-deriving test scaffolding per fix.

See also: testing — bug fixes land with a regression test in `tests/regressions/`.
