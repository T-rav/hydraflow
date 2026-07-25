---
id: 0763
topic: gotchas
source_issue: 10488
source_phase: review
created_at: 2026-07-25T00:38:26.060759+00:00
status: stale
corroborations: 1
stale_reason: source issue #10488 closed
---

# StreamView counts must reuse toStreamIssue's repo-qualified join, not re-lookup

`countPipeline`/`countRegion` (`src/ui/src/utils/pipelineCounts.js`) read `issue.pr` from the join already done in `toStreamIssue` (`StreamView.jsx:249-254`) rather than doing a second, repo-blind PR lookup. A second lookup risks matching a PR from the wrong repo when issue/PR numbers collide across repos. Any new derived-count helper for StreamView should consume the already-qualified `issue.pr` field, never re-resolve PRs by number alone.

**Why:** a repo-blind second lookup would silently produce wrong counts whenever two repos share a PR number.
