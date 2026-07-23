---
id: 0341
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T17:02:49.506193+00:00
status: superseded
corroborations: 1
supersedes: 0327,0328,0329,0330,0331,0332,0333,0334,0335,0336
superseded_by: 0348
---

# Bug-fix regressions use LoopDeps + Fake* adapters under tests/regressions/

Follow the established pattern for new regression coverage: direct loop instantiation using `LoopDeps` wired to `Fake*` adapters (e.g. `FakeGithub`), placed under `tests/regressions/` — not a separate `tests/scenarios/` file unless the bug is loop-integration-shaped.

Example: matches prior precedent like `regression_issue_10225.py`.

**Why:** Keeps regression coverage lightweight and consistent so reviewers recognize the pattern immediately instead of re-deriving test scaffolding per fix.

See also: testing — bug fixes land with a regression test in `tests/regressions/`.
