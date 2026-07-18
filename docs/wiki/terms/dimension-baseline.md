---
id: "01KWFR9AWM3NX19D0C1W10NNMN"
name: "DimensionBaseline"
kind: "control_role"
bounded_context: "shared-kernel"
code_anchor: "src/disturbance/registry.py:DimensionSpec"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-01T21:10:16.212905+00:00"
updated_at: "2026-07-01T21:10:16.212906+00:00"
---

## Definition

The Set-point (ADR-0094) for one disturbance dimension in the Disturbance Dampener (ADR-0095): a version-controlled, count-per-signature YAML snapshot (disturbance/baselines/<dimension>.yaml) of a dimension's known violations at the point it was last accepted. DimensionSpec is the registry entry binding a dimension's name, its ViolationDetector, its baseline path, and its fix prompt. The feedforward ratchet gate (src/disturbance/gate.py:run_gate) diffs a fresh detector pass against this baseline: any signature exceeding its baselined count is new and blocks the PR; a signature below its baselined count is burn-down progress. DisturbanceDampenerLoop's fix agents are instructed to prune resolved signatures from this baseline as part of each fix.

## Invariants

- A baseline only blocks growth past its recorded per-signature count; it never requires the pre-existing backlog to be cleared before the gate can be enabled for a dimension.
- Pruning a baseline entry without actually fixing the underlying violation is self-correcting: the next gate run re-diffs the detector's live findings against the pruned baseline and reports the signature as new, blocking the PR.
