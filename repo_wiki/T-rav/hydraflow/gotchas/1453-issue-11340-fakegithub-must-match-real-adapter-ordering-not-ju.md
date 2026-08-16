---
id: 1453
topic: gotchas
source_issue: 11340
source_phase: plan
created_at: 2026-08-16T11:56:57.838029+00:00
status: active
corroborations: 1
---

# FakeGitHub must match real adapter ordering, not just limits

When `gh issue list` returns newest-first, `FakeGitHub` listing methods must sort issue-number-descending before slicing to the window limit. An insertion-order slice drops the wrong end.

- `list_issues_by_label`, `list_open_issues`, and `list_closed_issues_by_label` in `src/mockworld/fakes/fake_github.py` all need number-desc sort before their slice.
- `list_closed_issues_by_label` already claimed "most recent" in its docstring but returned dict-insertion order.

**Why:** Without matching ordering, window-truncation defects like #11333 are structurally invisible at the MockWorld tier — the fake drops different rows than production.
