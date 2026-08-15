---
id: 2156
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T23:28:16.531115+00:00
status: superseded
corroborations: 1
supersedes: 2040,2064
superseded_by: 2272
---

# Immutability check needs merge-base range AND per-record ls-tree set

For `scripts/check_console_conformance.py` check #6, a rev range alone (`<merge_base>..HEAD`) is insufficient. Resolve the branch point via `git merge-base`, then `git ls-tree -r --name-only <mb> -- agents/console/decisions` to enumerate records present at base, and restrict `git log` to those exact paths. Records created after the merge-base are exempt.

Example: An in-PR typo fix on a record the same PR created would still flag under rev-range-only scoping; the per-record exemption is load-bearing.

**Why:** Rev-range-only scoping either flags legitimate in-PR drafting or misses post-merge modifications — the per-record exemption prevents both.
