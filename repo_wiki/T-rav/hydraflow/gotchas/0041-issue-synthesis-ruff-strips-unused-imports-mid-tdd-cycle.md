---
id: 0041
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.698454+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Ruff strips unused imports mid-TDD cycle

During TDD, write the test body (which uses the new symbol) before adding its import — or use a function-local import inside the test body.

Example: add `from scripts.audit import score_rule` only after `score_rule` appears in the test function body. Alternative: `def test_score(): from scripts.audit import score_rule; assert score_rule(...)`.

**Why:** Pre-commit `ruff --fix` removes imports not yet referenced on the first save, producing `NameError` on the second save and breaking the TDD red-phase.

See also: Testing — feedback memory `feedback_ruff_strips_unused_imports_during_tdd.md`.
