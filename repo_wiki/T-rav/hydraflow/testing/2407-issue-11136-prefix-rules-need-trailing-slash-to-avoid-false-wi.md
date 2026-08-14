---
id: 2407
topic: testing
source_issue: 11136
source_phase: plan
created_at: 2026-08-14T13:02:38.765840+00:00
status: active
corroborations: 1
---

# Prefix rules need trailing slash to avoid false widening

When adding prefix-based full-suite triggers in `_hard_full_suite_reason`, always include the trailing slash: `.claude/`, not `.claude`. Without it, `.claudeignore` and `.claude-cache` silently widen the trigger. Guard with a negative test asserting `select_tests([".claudeignore"], …)` returns `(frozenset(), None)`.

**Why:** A bare prefix without the slash is an invisible widening bug that no positive test will catch.
