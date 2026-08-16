---
id: 1406
topic: gotchas
source_issue: 11275
source_phase: plan
created_at: 2026-08-15T20:45:30.666404+00:00
status: active
corroborations: 1
---

# Branch GC namespace widening requires two coordinated sites

When widening branch-GC namespace coverage, update both `_AGENT_BRANCH_RE` in `src/branch_gc_scan.py` AND `_BRANCH_GC_PREFIXES` in `src/stale_issue_loop.py`. Changing the regex alone is a no-op: the inventory tuple gates which branches get queried via `gh api matching-refs`, so unmatched prefixes are never inventoried regardless of regex support.

Example: adding `agent/auto-agent-` to the regex without adding `AUTO_AGENT_BRANCH_PREFIX` to the tuple → zero behavior change, zero test failures.

**Why:** The two sites are coupled but not co-located; a one-site change silently does nothing.
