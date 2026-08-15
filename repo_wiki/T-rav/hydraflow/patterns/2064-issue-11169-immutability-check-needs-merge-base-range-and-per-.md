---
id: 2064
topic: patterns
source_issue: 11169
source_phase: plan
created_at: 2026-08-14T19:43:33.955250+00:00
status: superseded
corroborations: 1
superseded_by: 2156
---

# Immutability check needs merge-base range AND per-record ls-tree set

For `scripts/check_console_conformance.py` check #6, a rev range alone (`<merge_base>..HEAD`) is insufficient. An in-PR typo fix on a record the same PR created would still flag.

Resolve the branch point via `git merge-base <cand> HEAD`, then `git ls-tree -r --name-only <mb> -- agents/console/decisions` to enumerate records present at base, and restrict `git log` to those exact paths.

**Why:** Rev-range-only scoping leaves the in-PR-draft regression RED; the per-record exemption is load-bearing, not optional.
