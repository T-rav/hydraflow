---
id: 1193
topic: gotchas
source_issue: 10747
source_phase: legacy-migrated
created_at: 2026-07-28T00:20:21.241273+00:00
status: active
corroborations: 1
---

# Shipped with known gap — PR #10759

# Shipped with known gap — PR #10759

PR #10759 merged with 5 unresolved adversarial concern(s) that survived all gates without an explicit ConcernResolution. Future planners / reviewers should treat these as known gaps until either addressed in a follow-up PR or explicitly accepted.

## Unresolved concerns

- **HIGH** `PLAN-ASSUMP-001` (raised in `plan` / `assumption_surfacer`): Attribution confidence is explicitly marked 'low'. The blame-intersect method may have incorrectly identified the prior change this hotfix relates to. Validation needed: does this hotfix actually address the identified prior change, or is the root cause different?
  - _must_address_by_: `planner`
- **HIGH** `PLAN-ASSUMP-002` (raised in `plan` / `assumption_surfacer`): Mechanism assumption: the `make escape-resolve` CLI must correctly append a resolution row to the escape ledger and the EscapeLedgerLoop must correctly process it on the next tick to auto-close this issue. Validate CLI behavior and ledger append semantics (per ADR conventions on append-only ledger semantics) in a spike before committing to this resolution path.
  - _must_address_by_: `planner`
- **MEDIUM** `PLAN-ASSUMP-003` (raised in `plan` / `assumption_surfacer`): The issue states the escape 'already became work through normal triage' but provides no visibility into what that work was, when it merged, or what it addressed. Verify the related work is merged and complete before encoding the resolution.
  - _must_address_by_: `planner`
- **MEDIUM** `PLAN-ASSUMP-004` (raised in `plan` / `assumption_surfacer`): Insufficient context to determine which of the four encoding types is appropriate (regression-test vs stored-lesson vs detector vs adr). The issue notes only 'Hotfix referencing a prior merged change' without describing the nature of the original failure, why the hotfix was needed, or what pattern should be captured.
  - _must_address_by_: `planner`
- **LOW** `PLAN-ASSUMP-005` (raised in `plan` / `assumption_surfacer`): The git relationship between the hotfix commit and prior change is unclear (cherry-pick, revert, fix-on-top, etc.). Understanding the git lineage may inform encoding choice and validate the blame-intersect attribution.
  - _must_address_by_: `planner`

```json:entry
{"id": "shipped-with-known-gap-pr-10759", "title": "Shipped with known gap \u2014 PR #10759", "topic": "gotchas", "source_type": "shipped-with-known-gap", "source_issue": null, "source_repo": null, "pr_number": 10759, "created_at": "2026-07-28T00:20:21.241237+00:00", "updated_at": "2026-07-28T00:20:21.241237+00:00", "valid_to": null, "superseded_by": null, "superseded_reason": null, "confidence": "high", "stale": false, "corroborations": 1, "concerns": [{"id": "PLAN-ASSUMP-001", "severity": "HIGH", "concern": "Attribution confidence is explicitly marked 'low'. The blame-intersect method may have incorrectly identified the prior change this hotfix relates to. Validation needed: does this hotfix actually address the identified prior change, or is the root cause different?", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-002", "severity": "HIGH", "concern": "Mechanism assumption: the `make escape-resolve` CLI must correctly append a resolution row to the escape ledger and the EscapeLedgerLoop must correctly process it on the next tick to auto-close this issue. Validate CLI behavior and ledger append semantics (per ADR conventions on append-only ledger semantics) in a spike before committing to this resolution path.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-003", "severity": "MEDIUM", "concern": "The issue states the escape 'already became work through normal triage' but provides no visibility into what that work was, when it merged, or what it addressed. Verify the related work is merged and complete before encoding the resolution.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-004", "severity": "MEDIUM", "concern": "Insufficient context to determine which of the four encoding types is appropriate (regression-test vs stored-lesson vs detector vs adr). The issue notes only 'Hotfix referencing a prior merged change' without describing the nature of the original failure, why the hotfix was needed, or what pattern should be captured.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-005", "severity": "LOW", "concern": "The git relationship between the hotfix commit and prior change is unclear (cherry-pick, revert, fix-on-top, etc.). Understanding the git lineage may inform encoding choice and validate the blame-intersect attribution.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}]}
```

