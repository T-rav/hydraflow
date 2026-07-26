---
id: 1139
topic: gotchas
source_issue: 10591
source_phase: plan
created_at: 2026-07-26T03:23:10.272131+00:00
status: superseded
corroborations: 1
superseded_by: 1144
---

# GitHub-issue audit scripts route through PRPort, never raw gh/git/subprocess

One-shot scripts that close already-filed GitHub issues/escalations (e.g. `scripts/audit_wiki_rot_false_positives.py`) must default to `--dry-run` with `--apply` opt-in, like `[[repo_wiki_data_repair_script_conventions]]` — but unlike those tree-repair scripts, this class performs zero file mutation. All GitHub reads/writes go through `PRPort` (`list_issues_by_label`, `list_closed_issues_by_label`, `close_issue`); a direct `gh` or `git` call in the script fails review. Issues carrying the label but with an unparseable body (operator-authored) are left open and reported as skipped, mirroring `EscalationReconciler`'s existing contract.

**Why:** hexagonal boundary enforcement — scripts that shell out to `gh`/`git` bypass `PRPort`'s testability and audit trail, and can't be exercised against an `AsyncMock` in `tests/test_audit_wiki_rot_false_positives.py`.
