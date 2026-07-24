---
id: 0592
topic: testing
source_issue: 10307
source_phase: plan
created_at: 2026-07-24T04:05:15.039814+00:00
status: active
corroborations: 1
---

# Test HITL-status color on a non-hitl stage key, not the hitl key

When testing `StreamCard.jsx` status-color branches, assert on a stage whose `meta.color` differs from the target status color — e.g. force `status: 'hitl'` on the `review` stage (meta orange) rather than the `hitl` stage (meta already red). Example: `makeIssue()` with a `review` stage overridden to `{ status: 'hitl' }`, then assert `getByTestId('stage-node-review').style.background === theme.red`.

**Why:** asserting on the `hitl` stage key passes even if the source branch is deleted or still resolves via `meta.color`, since that stage's meta color is coincidentally red — the test would give false confidence.
