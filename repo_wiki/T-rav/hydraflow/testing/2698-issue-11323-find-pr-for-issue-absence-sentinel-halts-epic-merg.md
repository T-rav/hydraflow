---
id: 2698
topic: testing
source_issue: 11323
source_phase: plan
created_at: 2026-08-16T09:14:32.109962+00:00
status: active
corroborations: 1
---

# find_pr_for_issue absence sentinel halts epic merge bundles

Treat `find_pr_for_issue` returning `0` as an operational signal, not just a display value.
- `epic.py:1423` uses it in `merge_epic_bundle`; `0` triggers `no_pr` and halts the bundle.
- Any change to PR-lookup coverage (e.g. adding Auto-Agent branch fallback) affects epic merge coordination, not just HITL dashboard rendering.

**Why:** The `0` sentinel's blast radius extends past display into merge orchestration, so lookup changes must be validated against `tests/test_epic_merge_coordination.py`.
