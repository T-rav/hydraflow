---
id: 1367
topic: gotchas
source_issue: 11178
source_phase: legacy-migrated
created_at: 2026-08-15T02:13:18.889201+00:00
status: stale
corroborations: 1
stale_reason: source issue #11178 closed
---

# Shipped with known gap — PR #11197

# Shipped with known gap — PR #11197

PR #11197 merged with 3 unresolved adversarial concern(s) that survived all gates without an explicit ConcernResolution. Future planners / reviewers should treat these as known gaps until either addressed in a follow-up PR or explicitly accepted.

## Unresolved concerns

- **HIGH** `PLAN-ASSUMP-001` (raised in `plan` / `assumption_surfacer`): `make escape-resolve` behavior unverified: the make target must exist, properly append resolution rows, and trigger auto-close via EscapeLedgerLoop. Per mechanism assumption rule, subprocess command behavior is load-bearing and frequently wrong.
  - _must_address_by_: `planner`
- **HIGH** `PLAN-ASSUMP-002` (raised in `plan` / `assumption_surfacer`): Regression test pins (tests/regressions/test_issue_*.py) are untracked in git. Planner must verify whether these files must be committed before running `make escape-resolve`, or if the ledger system can reference uncommitted paths.
  - _must_address_by_: `planner`
- **MEDIUM** `PLAN-ASSUMP-003` (raised in `plan` / `assumption_surfacer`): Attribution confidence is medium, so the root cause mapping to a single encoding type (regression-test vs. stored-lesson vs. detector vs. adr) may be uncertain. Incorrect encoding choice could leave the escape open or cause re-firing.
  - _must_address_by_: `planner`

```json:entry
{"id": "shipped-with-known-gap-pr-11197", "title": "Shipped with known gap \u2014 PR #11197", "topic": "gotchas", "source_type": "shipped-with-known-gap", "source_issue": null, "source_repo": null, "pr_number": 11197, "created_at": "2026-08-15T02:13:18.889156+00:00", "updated_at": "2026-08-15T02:13:18.889156+00:00", "valid_to": null, "superseded_by": null, "superseded_reason": null, "confidence": "high", "stale": false, "corroborations": 1, "concerns": [{"id": "PLAN-ASSUMP-001", "severity": "HIGH", "concern": "`make escape-resolve` behavior unverified: the make target must exist, properly append resolution rows, and trigger auto-close via EscapeLedgerLoop. Per mechanism assumption rule, subprocess command behavior is load-bearing and frequently wrong.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-002", "severity": "HIGH", "concern": "Regression test pins (tests/regressions/test_issue_*.py) are untracked in git. Planner must verify whether these files must be committed before running `make escape-resolve`, or if the ledger system can reference uncommitted paths.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-003", "severity": "MEDIUM", "concern": "Attribution confidence is medium, so the root cause mapping to a single encoding type (regression-test vs. stored-lesson vs. detector vs. adr) may be uncertain. Incorrect encoding choice could leave the escape open or cause re-firing.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}]}
```

