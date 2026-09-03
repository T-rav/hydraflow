---
id: 1570
topic: gotchas
source_issue: 12058
source_phase: plan
created_at: 2026-09-02T22:01:19.186928+00:00
status: active
corroborations: 1
---

# Closed-issue detection requires explicit API call

Absence from the open issue list is ambiguous—the issue could be closed or its label removed. Use `list_closed_issues_by_label` carrying both `labels` and `closed_at` to distinguish a close from a label change.

Example: Query closed issues explicitly before reversion; only revert rows whose issues appear in the closed list with a recent `closed_at`.

**Why:** Label-only changes would look like closes; incorrect reversion re-files settled rows and spams the board.
