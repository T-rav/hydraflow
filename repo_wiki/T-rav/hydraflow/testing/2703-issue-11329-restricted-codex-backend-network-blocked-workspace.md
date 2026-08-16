---
id: 2703
topic: testing
source_issue: 11329
source_phase: plan
created_at: 2026-08-16T09:40:01.182610+00:00
status: active
corroborations: 1
---

# Restricted codex backend = network-blocked workspace-write

When `review_tool`/`ac_tool` is `codex`, restricted mode yields `codex exec --json --model …` under `workspace-write` with network blocked, not `acceptEdits`.

- `tests/test_reviewer.py::test_build_command_supports_codex_backend` must stay green after threading `restricted=`.
- The optional `gh api code-scanning` hint at `src/reviewer.py:104` degrades on codex only.
- Both `review_tool` and `ac_tool` default to `claude`.

**Why:** Codex has no `bypassPermissions`/`acceptEdits` flag pair; the equivalent trust boundary is the workspace-write sandbox tier, and ignoring this breaks the codex test pin.
