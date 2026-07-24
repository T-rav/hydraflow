---
id: 0694
topic: gotchas
source_issue: 10455
source_phase: plan
created_at: 2026-07-24T12:32:23.750694+00:00
status: superseded
corroborations: 1
superseded_by: 0704
---

# Untracked near-duplicate regression test drafts trip jscpd — land only the matching one

When two near-identical local drafts exist for overlapping issues (e.g. `test_issue_10411.py` and `test_issue_10455.py` both testing `_SHARED_INFRA_MODULES` behavior), commit only the one matching the current issue's number and the `test_issue_NNNNN.py` convention. **Why:** shipping both duplicate files trips `make quality`'s jscpd duplication check, turning a clean tactical slice into a CI failure.
