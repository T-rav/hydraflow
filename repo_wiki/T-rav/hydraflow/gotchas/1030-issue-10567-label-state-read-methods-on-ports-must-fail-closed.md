---
id: 1030
topic: gotchas
source_issue: 10567
source_phase: plan
created_at: 2026-07-25T23:37:32.613886+00:00
status: stale
corroborations: 1
stale_reason: source issue #10567 closed
---

# Label/state read methods on Ports must fail-closed, not return []

`get_issue_labels` (src/pr_manager.py:1915) and its `get_pr_labels` sibling propagate `gh` failures (RuntimeError) rather than catching and returning `[]`. Wrapping the read in `try/except: return []` "for safety" inverts the contract: a label-based routing feature (e.g. a `review:ultra` opt-in) would silently never fire instead of surfacing the error.
**Why:** fail-open on a routing-critical read turns a visible `gh` outage into a silent mis-route.
