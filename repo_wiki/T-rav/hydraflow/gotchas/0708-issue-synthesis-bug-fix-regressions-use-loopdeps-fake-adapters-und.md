---
id: 0708
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:44:15.946005+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# Bug-fix regressions use LoopDeps + Fake* adapters under tests/regressions/

Follow the established pattern for new regression coverage: direct loop instantiation using `LoopDeps` wired to `Fake*` adapters (e.g. `FakeGithub`), placed under `tests/regressions/` — not a separate `tests/scenarios/` file unless the bug is loop-integration-shaped.

Example: matches prior precedent like `regression_issue_10225.py`.

**Why:** Keeps regression coverage lightweight and consistent so reviewers recognize the pattern immediately instead of re-deriving test scaffolding per fix.

See also: testing — bug fixes land with a regression test in `tests/regressions/`.
