---
id: 0502
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T09:43:13.305631+00:00
status: active
corroborations: 1
supersedes: 0492,0493,0494,0495,0496,0497,0498,0499
---

# Sync test label constants with production label definitions

Keep test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) synchronized with production definitions (ADR-0002 label state machine) via a sync test asserting set equality.

Example: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`.

**Why:** Stale test constants let new label additions pass CI without being exercised by the test suite.
