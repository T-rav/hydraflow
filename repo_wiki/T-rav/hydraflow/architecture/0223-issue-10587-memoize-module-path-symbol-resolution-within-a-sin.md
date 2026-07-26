---
id: 0223
topic: architecture
source_issue: 10587
source_phase: plan
created_at: 2026-07-26T02:52:52.792539+00:00
status: active
corroborations: 1
---

# Memoize (module_path, symbol) resolution within a single lint pass

`shipped_claim_corroborated()` (src/wiki_rot_citations.py) resolves `code_refs` like `path.py:Symbol` via `ast.parse` + substring read. `active_lint_tracked` in `src/repo_wiki.py` only runs this for entries that are active, closed-sourced, AND carry a `fixed_in_pr` claim — but repeated refs across a topic's entries are common, so cache `(module_path, symbol) -> bool` for the duration of one lint call rather than re-parsing the same file per entry.
**Why:** unbounded `ast.parse` calls per tracked entry scale with topic size and add real latency to a maintenance tick with no cache.
