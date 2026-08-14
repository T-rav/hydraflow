---
id: 1350
topic: gotchas
source_issue: 11182
source_phase: plan
created_at: 2026-08-14T23:30:09.293989+00:00
status: active
corroborations: 1
---

# GC _ISSUE_BRANCH_RES needs re.escape and negative-case pins

`WorkspaceGCLoop._ISSUE_BRANCH_RES` is a class-level constant compiled at import. Building a new pattern entry from a config constant without `re.escape`, or with a trailing-`-` that overlaps the existing `fix|feat|…` pattern, silently mis-parses branch names.

- Pin: `_parse_issue_from_branch("agent/auto-agent-foo")` and `"agent/auto-agent-12/x"` both return `None` (fail-closed)
- Pin: `_parse_issue_from_branch(config.auto_agent_branch_for_issue(N)) == N`

**Why:** A regex compiled once at import with an un-escaped or overlapping prefix will match branches it shouldn't, attributing garbage to issue numbers and altering destructive GC sweeps.
