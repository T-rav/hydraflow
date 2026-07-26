---
id: 1052
topic: gotchas
source_issue: 10567
source_phase: legacy-migrated
created_at: 2026-07-26T02:27:55.452299+00:00
status: active
corroborations: 1
---

# Shipped with known gap — PR #10584

# Shipped with known gap — PR #10584

PR #10584 merged with 3 unresolved adversarial concern(s) that survived all gates without an explicit ConcernResolution. Future planners / reviewers should treat these as known gaps until either addressed in a follow-up PR or explicitly accepted.

## Unresolved concerns

- **HIGH** `PLAN-ASSUMP-001` (raised in `plan` / `assumption_surfacer`): gh command mechanism: assumes 'gh pr view' or equivalent reliably returns PR labels with the expected JSON structure. Validate in a scratch repo or minimal spike before committing to this mechanism in the plan.
  - _must_address_by_: `planner`
- **MEDIUM** `PLAN-ASSUMP-002` (raised in `plan` / `assumption_surfacer`): Caching strategy undefined: whether get_pr_labels should cache results (like list_prs_by_label) or fetch fresh each time. Affects correctness if labels change during loop execution.
  - _must_address_by_: `planner`
- **MEDIUM** `PLAN-ASSUMP-003` (raised in `plan` / `assumption_surfacer`): Return type contract unstated: assuming get_pr_labels return type matches get_issue_labels exactly. Label structure differences between PR and issue labels could break downstream routing logic.
  - _must_address_by_: `planner`

```json:entry
{"id": "shipped-with-known-gap-pr-10584", "title": "Shipped with known gap \u2014 PR #10584", "topic": "gotchas", "source_type": "shipped-with-known-gap", "source_issue": null, "source_repo": null, "pr_number": 10584, "created_at": "2026-07-26T02:27:55.452251+00:00", "updated_at": "2026-07-26T02:27:55.452251+00:00", "valid_to": null, "superseded_by": null, "superseded_reason": null, "confidence": "high", "stale": false, "corroborations": 1, "concerns": [{"id": "PLAN-ASSUMP-001", "severity": "HIGH", "concern": "gh command mechanism: assumes 'gh pr view' or equivalent reliably returns PR labels with the expected JSON structure. Validate in a scratch repo or minimal spike before committing to this mechanism in the plan.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-002", "severity": "MEDIUM", "concern": "Caching strategy undefined: whether get_pr_labels should cache results (like list_prs_by_label) or fetch fresh each time. Affects correctness if labels change during loop execution.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-003", "severity": "MEDIUM", "concern": "Return type contract unstated: assuming get_pr_labels return type matches get_issue_labels exactly. Label structure differences between PR and issue labels could break downstream routing logic.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}]}
```

