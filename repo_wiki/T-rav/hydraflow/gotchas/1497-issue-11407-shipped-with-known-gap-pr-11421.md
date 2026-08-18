---
id: 1497
topic: gotchas
source_issue: 11407
source_phase: legacy-migrated
created_at: 2026-08-18T04:13:01.446142+00:00
status: stale
corroborations: 1
stale_reason: source issue #11407 closed
---

# Shipped with known gap — PR #11421

# Shipped with known gap — PR #11421

PR #11421 merged with 6 unresolved adversarial concern(s) that survived all gates without an explicit ConcernResolution. Future planners / reviewers should treat these as known gaps until either addressed in a follow-up PR or explicitly accepted.

## Unresolved concerns

- **HIGH** `PLAN-ASSUMP-001` (raised in `plan` / `assumption_surfacer`): Mechanism assumption: `extract_folded_sites` behavior is claimed but not verified in context. Assumption that it yields title text as identifiers for legacy lines must be validated before designing the fix.
  - _must_address_by_: `planner`
- **HIGH** `PLAN-ASSUMP-002` (raised in `plan` / `assumption_surfacer`): Mechanism assumption: The data structure of `existing_sites` and how the `in` operator behaves on it is unverified. `title in existing_sites` could have different semantics depending on whether it's a set, dict, or list.
  - _must_address_by_: `planner`
- **HIGH** `PLAN-ASSUMP-003` (raised in `plan` / `assumption_surfacer`): The collision scenario (different site, same title text) is described as 'plausible' but has no regression test and no evidence it manifests in practice. Before committing to the fix, reproduce the collision in a test case to confirm it's real.
  - _must_address_by_: `planner`
- **MEDIUM** `PLAN-ASSUMP-004` (raised in `plan` / `assumption_surfacer`): Unclear whether `title in existing_sites` was intentional design to handle legacy rediscovery or an accidental bug introduced in the PR. Code review or commit message context could clarify the intent.
  - _must_address_by_: `planner`
- **MEDIUM** `PLAN-ASSUMP-005` (raised in `plan` / `assumption_surfacer`): Impact scope not quantified. How many class issues are affected by silent site-drop in production? The finding shows the mechanism but not prevalence.
  - _must_address_by_: `planner`
- **LOW** `PLAN-ASSUMP-006` (raised in `plan` / `assumption_surfacer`): The title-based dedup logic needs explanation. Why is title matching acceptable as a proxy for 'same site' in legacy handling when it provably collides?
  - _must_address_by_: `planner`

```json:entry
{"id": "shipped-with-known-gap-pr-11421", "title": "Shipped with known gap \u2014 PR #11421", "topic": "gotchas", "source_type": "shipped-with-known-gap", "source_issue": null, "source_repo": null, "pr_number": 11421, "created_at": "2026-08-18T04:13:01.446088+00:00", "updated_at": "2026-08-18T04:13:01.446088+00:00", "valid_to": null, "superseded_by": null, "superseded_reason": null, "confidence": "high", "stale": false, "corroborations": 1, "concerns": [{"id": "PLAN-ASSUMP-001", "severity": "HIGH", "concern": "Mechanism assumption: `extract_folded_sites` behavior is claimed but not verified in context. Assumption that it yields title text as identifiers for legacy lines must be validated before designing the fix.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-002", "severity": "HIGH", "concern": "Mechanism assumption: The data structure of `existing_sites` and how the `in` operator behaves on it is unverified. `title in existing_sites` could have different semantics depending on whether it's a set, dict, or list.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-003", "severity": "HIGH", "concern": "The collision scenario (different site, same title text) is described as 'plausible' but has no regression test and no evidence it manifests in practice. Before committing to the fix, reproduce the collision in a test case to confirm it's real.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-004", "severity": "MEDIUM", "concern": "Unclear whether `title in existing_sites` was intentional design to handle legacy rediscovery or an accidental bug introduced in the PR. Code review or commit message context could clarify the intent.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-005", "severity": "MEDIUM", "concern": "Impact scope not quantified. How many class issues are affected by silent site-drop in production? The finding shows the mechanism but not prevalence.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-006", "severity": "LOW", "concern": "The title-based dedup logic needs explanation. Why is title matching acceptable as a proxy for 'same site' in legacy handling when it provably collides?", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}]}
```

