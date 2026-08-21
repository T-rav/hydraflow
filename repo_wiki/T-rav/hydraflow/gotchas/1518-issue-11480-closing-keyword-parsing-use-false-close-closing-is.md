---
id: 1518
topic: gotchas
source_issue: 11480
source_phase: plan
created_at: 2026-08-20T06:54:25.786690+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Closing-keyword parsing: use false_close.closing_issue_refs, not _FIXES_RE

Parse GitHub closing keywords via `false_close.closing_issue_refs` (public, full closing-verb regex; `Fixes #7:` parses). Avoid `branch_gc_scan._FIXES_RE` — underscore-private and first-match-only.

Example: `issue_number in closing_issue_refs(m)` over commit messages from `prs.list_branch_commits(...)` and `ctx.recent_commits`.

**Why:** The private regex misses legitimate closing-verb forms and is not a stable public surface; using it produces false negatives in landed-fix detection.
