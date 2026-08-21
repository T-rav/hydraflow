---
id: 1525
topic: gotchas
source_issue: 11502
source_phase: plan
created_at: 2026-08-21T01:24:51.844609+00:00
status: active
corroborations: 1
---

# New PRPort reads mirror existing vocabulary and fail-closed contract

When adding a read to `PRPort` (e.g. `get_branch_pr_state`), mirror the vocabulary and fail-closed contract of an existing sibling method like `get_issue_state`. Return `MERGED|OPEN|CLOSED|NONE|UNKNOWN`; any read/parse failure returns `UNKNOWN` rather than raising. `FakeGitHub` must mirror the same semantics via the three-layer mirror rule.

**Why:** Inconsistent vocabulary or exception-raising in one Port implementation breaks the fail-closed guarantees that `WorkspaceGCLoop` relies on to never destroy unpushed work.
