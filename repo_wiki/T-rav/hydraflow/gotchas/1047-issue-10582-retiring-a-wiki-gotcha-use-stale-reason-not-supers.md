---
id: 1047
topic: gotchas
source_issue: 10582
source_phase: plan
created_at: 2026-07-26T02:05:19.449706+00:00
status: active
corroborations: 1
---

# Retiring a wiki gotcha: use `stale_reason`, not `superseded_by`

When a `repo_wiki/*/gotchas/*.md` entry's advice is spent but there's no replacement entry, flip `status: active` -> `stale` and add `stale_reason` naming the PRs that closed it out (e.g. `#10525` and `#10521`). Don't use `superseded_by` — that field implies a specific successor entry exists, which retire-without-replacement doesn't have. Leave the body intact; retiring is not deleting, it preserves the coordination record in git history.

**Why:** `superseded_by` pointing at nothing breaks whatever tooling resolves that link, and deleting loses the historical record.
