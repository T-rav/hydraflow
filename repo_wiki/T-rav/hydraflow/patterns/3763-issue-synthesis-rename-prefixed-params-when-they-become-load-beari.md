---
id: 3763
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T13:50:50.807456+00:00
status: superseded
corroborations: 1
supersedes: 3618
superseded_by: 3908
---

# Rename _-prefixed params when they become load-bearing branches

Rename a `_`-prefixed parameter when it becomes a branching condition; keep it positional-compatible with the base-class signature.

Example: `DiagnosticRunner._build_command` renamed `_worktree` to `worktree` once it branched read-only vs edit-capable, staying positional-compatible with `BaseRunner._build_command`.

**Why:** A `_` prefix signals "unused" — callers would ignore a load-bearing argument.
