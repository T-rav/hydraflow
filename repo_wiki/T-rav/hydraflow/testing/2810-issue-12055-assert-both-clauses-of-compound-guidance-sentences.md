---
id: 2810
topic: testing
source_issue: 12055
source_phase: plan
created_at: 2026-09-02T21:55:38.779830+00:00
status: active
corroborations: 1
---

# Assert both clauses of compound guidance sentences in tests

When a prompt or rule statement has two parts, assert both in test code, not just the enforced one.

Example: src/agent/_prompts.py:178 says "do not run `bd` in this worktree or edit it directly"; test_injects_ids_without_database_cli_commands only checks the `bd` clause, leaving the no-hand-edit half unpinned.

**Why:** Unpinned clauses drift unchecked; agents may follow one half while the other silently fails.
