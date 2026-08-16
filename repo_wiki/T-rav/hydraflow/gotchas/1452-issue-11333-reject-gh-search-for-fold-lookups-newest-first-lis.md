---
id: 1452
topic: gotchas
source_issue: 11333
source_phase: plan
created_at: 2026-08-16T11:30:55.516402+00:00
status: active
corroborations: 1
---

# Reject gh --search for fold lookups; newest-first listing is the source of truth

Do not use `gh issue list --search "findclass:<key> in:body"` as a fold-lookup remedy. GitHub parses an unquoted `findclass:` as an unknown qualifier and a quoted phrase changes body-matching semantics. Search-index latency also misses a just-created class issue.

- Use `gh issue list --label <label> --limit <N>` (newest-first) instead.
- Saturation is logged, not silently truncated.

**Why:** Search qualifier behavior is untestable in-repo and timing-dependent; the newest-first listing always sees a freshly created issue.
