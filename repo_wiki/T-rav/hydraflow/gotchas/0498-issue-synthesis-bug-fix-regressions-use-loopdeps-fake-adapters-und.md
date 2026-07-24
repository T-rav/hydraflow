---
id: 0498
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.773005+00:00
status: superseded
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
superseded_by: 0545
---

# Bug-fix regressions use LoopDeps + Fake* adapters under tests/regressions/

Follow the established pattern for new regression coverage: direct loop instantiation using `LoopDeps` wired to `Fake*` adapters (e.g. `FakeGithub`), placed under `tests/regressions/` — not a separate `tests/scenarios/` file unless the bug is loop-integration-shaped.

Example: matches prior precedent like `regression_issue_10225.py`.

**Why:** Keeps regression coverage lightweight and consistent so reviewers recognize the pattern immediately instead of re-deriving test scaffolding per fix.

See also: testing — bug fixes land with a regression test in `tests/regressions/`.
