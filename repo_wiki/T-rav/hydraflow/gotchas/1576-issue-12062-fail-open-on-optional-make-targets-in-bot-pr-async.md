---
id: 1576
topic: gotchas
source_issue: 12062
source_phase: plan
created_at: 2026-09-02T22:21:22.693530+00:00
status: active
corroborations: 1
---

# Fail open on optional make targets in bot PR async paths

Self-skip silently if `worktree/Makefile` is absent; convert runtime errors to warnings via `reraise_on_credit_or_bug` then `logger.warning`; never `return fail()`. Toy-repo unit tests and hosts without `make` must not break PR opens. Worst case: commit still fails with the pre-commit hook's existing message.
