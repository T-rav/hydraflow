---
id: 2715
topic: testing
source_issue: 11338
source_phase: plan
created_at: 2026-08-16T12:34:38.644986+00:00
status: active
corroborations: 1
---

# Fake factory defaults silently cross-contaminate issue-scoped data

When a fake coercion method (`FakeLLM._coerce_implement`) omits a field, it inherits the factory's hardcoded default rather than deriving from runtime context. `WorkerResultFactory.create` hardcodes `branch="agent/issue-42"` (`src/mockworld/fakes/_factories.py:47`), so any implement payload missing `branch` silently gets issue 42's branch.

Default to `config.branch_for_issue(N)` in the coercion layer; let explicit payload values still win.

**Why:** Omitted keys produce semantically wrong cross-issue data that passes type checks but contradicts the worktree/state, creating contradictions only caught by targeted regression tests.
