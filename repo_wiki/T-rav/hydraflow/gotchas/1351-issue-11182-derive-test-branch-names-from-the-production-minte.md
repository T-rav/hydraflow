---
id: 1351
topic: gotchas
source_issue: 11182
source_phase: plan
created_at: 2026-08-14T23:30:09.294007+00:00
status: active
corroborations: 1
---

# Derive test branch names from the production minter, not hardcoded literals

A regression test can pass for the wrong reason if it fabricates a branch name the parser happens to filter rather than exercising the name the loop actually mints.

- `test_issue_10459.py` used `agent/issue-88` (fabricated) instead of `agent/auto-agent-88` (real)
- The GC parser returned `None` for the real name, so the retry-window guard was never consulted — the test passed because parsing failed, not because the guard fired
- Tests should call `config.auto_agent_branch_for_issue(N)` or drive the minter directly

**Why:** Hardcoded names that don't match production minting hide parser gaps and let the next auditor re-file the same escape.
