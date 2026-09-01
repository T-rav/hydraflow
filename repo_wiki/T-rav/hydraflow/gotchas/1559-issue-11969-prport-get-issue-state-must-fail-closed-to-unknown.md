---
id: 1559
topic: gotchas
source_issue: 11969
source_phase: plan
created_at: 2026-09-01T11:15:55.080338+00:00
status: active
corroborations: 1
---

# PRPort get_issue_state must fail-closed to UNKNOWN, not mismatch

`PRPort.get_issue_state` collapses both 404 and transport error into `UNKNOWN`/`""`. An inconclusive read must leave the pin untouched — never reset it.

Example: during a `gh` outage, 23 live `issue-open` pins stay pinned and re-file nothing; only a confirmed-closed or confirmed-mismatched issue resets.

**Why:** Treating 404 as "mismatch" would mass-reset and re-file open issues during any GitHub availability dip. The issue's "404 counts as mismatch" clause was deliberately downgraded to "leave alone" — safety over completeness.
