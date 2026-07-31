---
id: 0287
topic: architecture
source_issue: 10889
source_phase: plan
created_at: 2026-07-31T10:36:59.292311+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# AST guard for mutable globals must filter to in-file mutated literals

When scanning `src/**/*.py` for mutable module-level globals, constrain the rule to mutable literals *and* evidence of in-file mutation (`global` statement, `.add`/`.append`, or subscript assignment). Without the mutation filter, ordinary module-level dict/list constants across all of `src/` over-fire and the guard becomes un-landable.

**Why:** A guard that fires on every `SOME_CONST = {}` at module scope cannot be baselined without exhausting the team.
