---
id: 1410
topic: gotchas
source_issue: 11182
source_phase: legacy-migrated
created_at: 2026-08-15T20:57:07.074799+00:00
status: active
corroborations: 1
---

# Shipped with known gap — PR #11272

# Shipped with known gap — PR #11272

PR #11272 merged with 4 unresolved adversarial concern(s) that survived all gates without an explicit ConcernResolution. Future planners / reviewers should treat these as known gaps until either addressed in a follow-up PR or explicitly accepted.

## Unresolved concerns

- **CRITICAL** `PLAN-ASSUMP-001` (raised in `plan` / `assumption_surfacer`): The regex `^agent/issue-(\d+)$` in `_collect_orphaned_branches` does NOT match the actual pattern `agent/auto-agent-{issue_number}` created by `src/auto_agent_preflight_loop.py:720`. Real auto-agent branches are filtered out by `if not match: continue` before the `_in_retry_window` guard is ever evaluated, meaning the guard is dead code for its stated purpose. The test proves no actual protection because it tests a fabricated scenario (`agent/issue-88`) that can never occur in production.
  - _must_address_by_: `planner`
- **HIGH** `PLAN-ASSUMP-002` (raised in `plan` / `assumption_surfacer`): The regression test `test_orphan_branch_skipped_for_active_auto_agent` is a falsification instrument: it purports to prove that phase 3 protects auto-agent branches during GC, but it tests an impossible scenario. The real `agent/auto-agent-*` pattern is never covered, masking that orphaned auto-agent branches are not actually cleaned up or protected by phase 3 (verified to still be true in HEAD post-PR #10708).
  - _must_address_by_: `planner`
- **HIGH** `PLAN-ASSUMP-003` (raised in `plan` / `assumption_surfacer`): Mechanism assumption: The PR assumes `_AGENT_BRANCH_RE` regex in `_collect_orphaned_branches` will match and filter the intended branch patterns. Validate in a scratch repo or with a minimal spike that the regex correctly matches real auto-agent branch names created by the system before committing to this pattern in the plan.
  - _must_address_by_: `planner`
- **MEDIUM** `PLAN-ASSUMP-004` (raised in `plan` / `assumption_surfacer`): The PR's claim that 'every GC phase honors the guard' for #10459 is true for phases 1/2 (worktree directory protection via `_is_safe_to_gc` issue-number check) but false for phase 3 (branch cleanup, where real auto-agent branches never reach the guard due to regex filtering). Clarify whether this is an oversight or intentional exclusion.
  - _must_address_by_: `planner`

```json:entry
{"id": "shipped-with-known-gap-pr-11272", "title": "Shipped with known gap \u2014 PR #11272", "topic": "gotchas", "source_type": "shipped-with-known-gap", "source_issue": null, "source_repo": null, "pr_number": 11272, "created_at": "2026-08-15T20:57:07.074747+00:00", "updated_at": "2026-08-15T20:57:07.074747+00:00", "valid_to": null, "superseded_by": null, "superseded_reason": null, "confidence": "high", "stale": false, "corroborations": 1, "concerns": [{"id": "PLAN-ASSUMP-001", "severity": "CRITICAL", "concern": "The regex `^agent/issue-(\\d+)$` in `_collect_orphaned_branches` does NOT match the actual pattern `agent/auto-agent-{issue_number}` created by `src/auto_agent_preflight_loop.py:720`. Real auto-agent branches are filtered out by `if not match: continue` before the `_in_retry_window` guard is ever evaluated, meaning the guard is dead code for its stated purpose. The test proves no actual protection because it tests a fabricated scenario (`agent/issue-88`) that can never occur in production.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-002", "severity": "HIGH", "concern": "The regression test `test_orphan_branch_skipped_for_active_auto_agent` is a falsification instrument: it purports to prove that phase 3 protects auto-agent branches during GC, but it tests an impossible scenario. The real `agent/auto-agent-*` pattern is never covered, masking that orphaned auto-agent branches are not actually cleaned up or protected by phase 3 (verified to still be true in HEAD post-PR #10708).", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-003", "severity": "HIGH", "concern": "Mechanism assumption: The PR assumes `_AGENT_BRANCH_RE` regex in `_collect_orphaned_branches` will match and filter the intended branch patterns. Validate in a scratch repo or with a minimal spike that the regex correctly matches real auto-agent branch names created by the system before committing to this pattern in the plan.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-004", "severity": "MEDIUM", "concern": "The PR's claim that 'every GC phase honors the guard' for #10459 is true for phases 1/2 (worktree directory protection via `_is_safe_to_gc` issue-number check) but false for phase 3 (branch cleanup, where real auto-agent branches never reach the guard due to regex filtering). Clarify whether this is an oversight or intentional exclusion.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}]}
```

