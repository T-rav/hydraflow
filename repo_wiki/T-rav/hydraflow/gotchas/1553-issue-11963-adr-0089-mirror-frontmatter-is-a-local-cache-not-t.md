---
id: 1553
topic: gotchas
source_issue: 11963
source_phase: plan
created_at: 2026-09-01T09:53:18.676775+00:00
status: active
corroborations: 1
---

# ADR-0089: mirror frontmatter is a local cache, not the guard

Treat `memory_backlog_mirror.py` frontmatter (`status`, `issue`) as a cache of GitHub state, not as the dedup guard. The durable guard is the open-issue query via `PRPort`.

- Losing frontmatter costs exactly one `list_issues_by_label` call to rebuild.
- Git write-back stays local (no push, no PR) per ADR-0089 Rule 3.
- `_commit_mirror_updates` heals stale frontmatter to `issue-open` + issue number.

**Why:** Re-cloning or resetting the factory workspace must not re-file open issues; the query is the source of truth, frontmatter is a performance cache.
