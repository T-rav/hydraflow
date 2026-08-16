---
id: 3191
topic: patterns
source_issue: 11303
source_phase: plan
created_at: 2026-08-16T04:31:48.835991+00:00
status: active
corroborations: 1
---

# Place loop safety checks before early-return paths in _do_work

Order check methods ahead of the corpus run in any `SkillPromptEvalLoop._do_work` so early-return branches (e.g. `no_cases`) cannot bypass them.

Example: `_check_token_drift()` is invoked **before** `_run_corpus()`, and its count feeds both return paths so the loop still reports even when the adversarial corpus is empty.

**Why:** A check placed after the early return is silently skipped whenever the corpus has nothing to do, leaving drift undetected at exactly the moment the loop is exercising adversarial inputs.
