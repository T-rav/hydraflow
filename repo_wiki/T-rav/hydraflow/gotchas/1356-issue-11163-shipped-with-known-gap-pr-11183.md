---
id: 1356
topic: gotchas
source_issue: 11163
source_phase: legacy-migrated
created_at: 2026-08-14T23:47:54.583286+00:00
status: active
corroborations: 1
---

# Shipped with known gap — PR #11183

# Shipped with known gap — PR #11183

PR #11183 merged with 3 unresolved adversarial concern(s) that survived all gates without an explicit ConcernResolution. Future planners / reviewers should treat these as known gaps until either addressed in a follow-up PR or explicitly accepted.

## Unresolved concerns

- **CRITICAL** `PLAN-ASSUMP-001` (raised in `plan` / `assumption_surfacer`): The audit claims select_findings_to_surface has a semantic mismatch: it gates on terminal_ids() (existence-based) before verdict_for() (validation-based) is called. Rows with unrecognized diagnosis strings are excluded from surfaces but never re-diagnosed, defeating the documented recovery path. **Planner must first verify this gap is real in the code** by tracing the call paths in select_findings_to_surface and comparing terminal_ids() logic against verdict_for().
  - _must_address_by_: `planner`
- **HIGH** `PLAN-ASSUMP-002` (raised in `plan` / `assumption_surfacer`): If the gap exists, the fix requires aligning semantics between the selection gate and verdict path. This requires a clear decision: should rows with unrecognized diagnosis strings be treated as undiagnosed (triggering re-diagnosis) or as permanently terminal? Validate whether both code paths should call verdict_for() before any exclusion logic.
  - _must_address_by_: `planner`
- **MEDIUM** `PLAN-ASSUMP-003` (raised in `plan` / `assumption_surfacer`): The fix scope should explicitly cover three scenarios: (1) rolling deploy forward-compatibility (future enum values), (2) data corruption, (3) schema migration gaps. The code documents scenario 1 as supported but the gate logic prevents it; clarify which scenarios the fix targets and whether any should fail-safe differently.
  - _must_address_by_: `planner`

```json:entry
{"id": "shipped-with-known-gap-pr-11183", "title": "Shipped with known gap \u2014 PR #11183", "topic": "gotchas", "source_type": "shipped-with-known-gap", "source_issue": null, "source_repo": null, "pr_number": 11183, "created_at": "2026-08-14T23:47:54.583247+00:00", "updated_at": "2026-08-14T23:47:54.583247+00:00", "valid_to": null, "superseded_by": null, "superseded_reason": null, "confidence": "high", "stale": false, "corroborations": 1, "concerns": [{"id": "PLAN-ASSUMP-001", "severity": "CRITICAL", "concern": "The audit claims select_findings_to_surface has a semantic mismatch: it gates on terminal_ids() (existence-based) before verdict_for() (validation-based) is called. Rows with unrecognized diagnosis strings are excluded from surfaces but never re-diagnosed, defeating the documented recovery path. **Planner must first verify this gap is real in the code** by tracing the call paths in select_findings_to_surface and comparing terminal_ids() logic against verdict_for().", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-002", "severity": "HIGH", "concern": "If the gap exists, the fix requires aligning semantics between the selection gate and verdict path. This requires a clear decision: should rows with unrecognized diagnosis strings be treated as undiagnosed (triggering re-diagnosis) or as permanently terminal? Validate whether both code paths should call verdict_for() before any exclusion logic.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}, {"id": "PLAN-ASSUMP-003", "severity": "MEDIUM", "concern": "The fix scope should explicitly cover three scenarios: (1) rolling deploy forward-compatibility (future enum values), (2) data corruption, (3) schema migration gaps. The code documents scenario 1 as supported but the gate logic prevents it; clarify which scenarios the fix targets and whether any should fail-safe differently.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "planner"}]}
```

