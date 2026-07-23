---
id: 0534
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T15:34:08.389159+00:00
status: superseded
corroborations: 1
supersedes: 0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530
superseded_by: 0542
---

# Sync test label constants with production label definitions

Keep test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) synchronized with production definitions (ADR-0002 label state machine) via a sync test asserting set equality.

Example: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`.

**Why:** Stale test constants let new label additions pass CI without being exercised by the test suite.
