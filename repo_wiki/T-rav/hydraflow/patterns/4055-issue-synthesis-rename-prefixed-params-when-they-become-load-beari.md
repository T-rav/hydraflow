---
id: 4055
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T17:41:45.183122+00:00
status: active
corroborations: 1
supersedes: 3908
---

# Rename _-prefixed params when they become load-bearing branches

Rename a `_`-prefixed parameter when it becomes a branching condition; keep it positional-compatible with the base-class signature.

Example: `DiagnosticRunner._build_command` renamed `_worktree` to `worktree` once it branched read-only vs edit-capable, staying positional-compatible with `BaseRunner._build_command`.

**Why:** A `_` prefix signals "unused" — callers would ignore a load-bearing argument.
