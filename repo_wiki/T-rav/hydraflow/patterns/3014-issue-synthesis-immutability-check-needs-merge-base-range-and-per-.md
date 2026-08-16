---
id: 3014
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T20:34:48.244295+00:00
status: active
corroborations: 1
supersedes: 2887
---

# Immutability check needs merge-base range AND per-record ls-tree set

For `scripts/check_console_conformance.py` check #6, a rev range alone (`<merge_base>..HEAD`) is insufficient. Resolve the branch point via `git merge-base`, then `git ls-tree -r --name-only <mb> -- agents/console/decisions` to enumerate records present at base, and restrict `git log` to those exact paths. Records created after the merge-base are exempt.

Example: An in-PR typo fix on a record the same PR created would still flag under rev-range-only scoping; the per-record exemption is load-bearing. See also: [patterns] — Pass -M explicitly in check #6; [patterns] — Widen check #6 --diff-filter to DMR.

**Why:** Rev-range-only scoping either flags legitimate in-PR drafting or misses post-merge modifications — the per-record exemption prevents both.
