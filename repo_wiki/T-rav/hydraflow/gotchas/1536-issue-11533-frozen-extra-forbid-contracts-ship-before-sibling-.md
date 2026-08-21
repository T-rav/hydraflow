---
id: 1536
topic: gotchas
source_issue: 11533
source_phase: plan
created_at: 2026-08-21T09:41:01.976112+00:00
status: active
corroborations: 1
---

# Frozen extra=forbid contracts ship before sibling consumers

Contracts shared across sibling issues ship first as a standalone frozen module: Pydantic `extra="forbid"`, schema-versioned, with identity invariants under test.
- `src/driver_contracts.py` (DriverLease, DirectorCommand, WorkerReceipt, WORKER_CATALOG, …) is consumed unchanged by #11535/#11537.
- Tests enforce JSON round-trip both directions, unknown-field rejection, expired-lease/stale-epoch failure, and model identity: a Literal `claude-sonnet`/`claude-opus` ModelRequirement paired with a GLM id is rejected.
**Why:** Downstream issues must not reshape shared contracts mid-flight; frozen shapes turn cross-issue drift into a test failure instead of a merge conflict.
