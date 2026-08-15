---
id: 1362
topic: gotchas
source_issue: 11188
source_phase: plan
created_at: 2026-08-15T00:25:53.081766+00:00
status: active
corroborations: 1
---

# Truth-comment wording must be namespace-aware, not generic

`build_truth_comment` must cite the actual resolution source. Today's text falsely claims a `Fixes #N` commit for auto-agent branches that have none.

- `src/branch_gc_scan.py` → `build_truth_comment`
- `agent/issue-*` / `fix/*` wording stays unchanged.
- Auto-agent comment cites branch name + age, never a closing-keyword commit.

**Why:** A comment that fabricates a commit reference misleads human reviewers and breaks audit trails for HITL decisions.
