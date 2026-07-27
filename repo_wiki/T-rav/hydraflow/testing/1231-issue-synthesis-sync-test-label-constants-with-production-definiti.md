---
id: 1231
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:02.989271+00:00
status: superseded
corroborations: 1
supersedes: 1157
superseded_by: 1305
---

# Sync test label constants with production definitions

Keep test constants (ALL_PIPELINE_LABELS, VALID_STAGES, VALID_TRANSITIONS) synchronized with production definitions (ADR-0002) via a sync test asserting set equality.

Example: `assert set(VALID_TRANSITIONS.keys()) == VALID_STAGES`.

**Why:** Stale test constants let new label additions pass CI without being exercised.
