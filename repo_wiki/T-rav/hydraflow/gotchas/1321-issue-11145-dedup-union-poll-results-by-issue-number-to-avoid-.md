---
id: 1321
topic: gotchas
source_issue: 11145
source_phase: plan
created_at: 2026-08-14T15:10:07.166506+00:00
status: active
corroborations: 1
---

# Dedup union-poll results by issue number to avoid double-counting

When readers poll multiple queue labels (configured root + legacy alias), merge results by issue number before processing. An issue carrying both roots must be dispatched/counted exactly once.

- `auto_agent_preflight_loop.py` `_poll_eligible_issues` and `_reconcile_closed_issues` dedup by issue number across the union set.
- `detector_calibration_loop.py` runs its closed scan per queue label through `GitHubDataCache`, then merges by issue number.
- The cap flag (`_SCAN_LIMIT`) is true if **any** label hit the cap **or** the merged scan is empty.

**Why:** Union polling multiplies `gh issue list` calls and can count one dual-labelled issue twice in calibration churn, inflating API cost and producing duplicate findings.
