---
id: 0406
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.285421+00:00
status: superseded
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
superseded_by: 0446
---

# Bug-fix regressions use LoopDeps + Fake* adapters under tests/regressions/

Follow the established pattern for new regression coverage: direct loop instantiation using `LoopDeps` wired to `Fake*` adapters (e.g. `FakeGithub`), placed under `tests/regressions/` — not a separate `tests/scenarios/` file unless the bug is loop-integration-shaped.

Example: matches prior precedent like `regression_issue_10225.py`.

**Why:** Keeps regression coverage lightweight and consistent so reviewers recognize the pattern immediately instead of re-deriving test scaffolding per fix.

See also: testing — bug fixes land with a regression test in `tests/regressions/`.
