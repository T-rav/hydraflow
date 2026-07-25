---
id: 0847
topic: gotchas
source_issue: 10509
source_phase: plan
created_at: 2026-07-25T05:02:36.104056+00:00
status: active
corroborations: 1
---

# PipelineIssueStatus vocabulary is queued|active|processing|hitl|merged only

Client code branching on `status: 'done'` or `'failed'` against pipeline snapshot data is checking values `PipelineIssueStatus` never emits — those statuses fall through to whatever the default branch is (often `queued`), silently misrendering. Before adding a status branch in UI derivation code (e.g. `StreamView.jsx`'s `toStreamIssue`), grep the actual enum in `src/models.py` rather than trusting existing test fixtures, which may themselves encode the fictional vocabulary (seen in `StreamView.test.jsx:294/310/650` using `status:'done'`).

**Why:** stale fixtures normalize a vocabulary mismatch, so tests pass while production renders the wrong UI state.
