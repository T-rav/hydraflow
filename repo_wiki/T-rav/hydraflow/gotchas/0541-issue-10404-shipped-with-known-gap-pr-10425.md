---
id: 0541
topic: gotchas
source_issue: 10404
source_phase: legacy-migrated
created_at: 2026-07-24T07:41:31.502665+00:00
status: stale
corroborations: 1
stale_reason: source issue #10404 closed
---

# Shipped with known gap — PR #10425

# Shipped with known gap — PR #10425

PR #10425 merged with 4 unresolved adversarial concern(s) that survived all gates without an explicit ConcernResolution. Future planners / reviewers should treat these as known gaps until either addressed in a follow-up PR or explicitly accepted.

## Unresolved concerns

- **HIGH** `PLAN-ASSUMP-001` (raised in `plan` / `assumption_surfacer`): Symbol semantic equivalence is unverified. Three distinct modules (audit, escape, intervention) may use `existing_ids` for domain-specific purposes despite name collision. Domain semantics must be validated before unifying.
  - _must_address_by_: `planner`
- **HIGH** `PLAN-ASSUMP-002` (raised in `plan` / `assumption_surfacer`): Mechanism assumption: ErosionMetricsLoop's symbol-tracking across three files in one commit is load-bearing to this finding. Validate the tool correctly identified all occurrences and no false negatives exist.
  - _must_address_by_: `planner`
- **MEDIUM** `PLAN-ASSUMP-003` (raised in `plan` / `assumption_surfacer`): Unification risk: extracting to a shared utility may create module-graph cycles or violate architectural independence rules. Check whether audit, escape, intervention are designed to have no mutual dependencies (per ADR-0021/0032).
  - _must_address_by_: `planner`
- **MEDIUM** `PLAN-ASSUMP-004` (raised in `plan` / `assumption_surfacer`): Heuristic maturity: issue labels this as 'v1 heuristic, PROVISIONAL'. False-positive rate and precision of the concept-scatter sensor are unvalidated; this may be one of several similar pattern instances or an anomaly.
  - _must_address_by_: `planner`

```json:entry
{"id": "shipped-with-known-gap-pr-10425", "title": "Shipped with known gap \u2014 PR #10425", "topic": "gotchas", "source_type": "shipped-with-known-gap", "source_issue": null, "source_repo": null, "pr_number": 10425, "created_at": "2026-07-24T07:41:31.502623+00:00", "updated_at": "2026-07-24T07:41:31.502623+00:00", "valid_to": null, "superseded_by": null, "superseded_reason": null, "confidence": "high", "stale": false, "corroborations": 1, "concerns": [{"id": "PLAN-ASSUMP-001", "severity": "HIGH", "concern": "Symbol semantic equivalence is unverified. Three distinct modules (audit, escape, intervention) may use `existing_ids` for domain-specific purposes despite name collision. Domain semantics must be validated before unifying.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-002", "severity": "HIGH", "concern": "Mechanism assumption: ErosionMetricsLoop's symbol-tracking across three files in one commit is load-bearing to this finding. Validate the tool correctly identified all occurrences and no false negatives exist.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-003", "severity": "MEDIUM", "concern": "Unification risk: extracting to a shared utility may create module-graph cycles or violate architectural independence rules. Check whether audit, escape, intervention are designed to have no mutual dependencies (per ADR-0021/0032).", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-004", "severity": "MEDIUM", "concern": "Heuristic maturity: issue labels this as 'v1 heuristic, PROVISIONAL'. False-positive rate and precision of the concept-scatter sensor are unvalidated; this may be one of several similar pattern instances or an anomaly.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}]}
```

