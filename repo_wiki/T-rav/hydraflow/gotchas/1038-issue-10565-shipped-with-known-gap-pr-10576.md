---
id: 1038
topic: gotchas
source_issue: 10565
source_phase: legacy-migrated
created_at: 2026-07-26T01:13:28.551613+00:00
status: active
corroborations: 1
---

# Shipped with known gap — PR #10576

# Shipped with known gap — PR #10576

PR #10576 merged with 3 unresolved adversarial concern(s) that survived all gates without an explicit ConcernResolution. Future planners / reviewers should treat these as known gaps until either addressed in a follow-up PR or explicitly accepted.

## Unresolved concerns

- **CRITICAL** `PLAN-ASSUMP-001` (raised in `plan` / `assumption_surfacer`): bare_infra_citation_nudges() has no ADR-status filter while compute_drift restricts to live ADRs only. The shipped artifact (docs/arch/generated/adr_xref.md lines 312-313) shows Superseded ADR-0013 being nudged despite never entering drift-suppression. This directly violates the PR's stated single-source-of-truth invariant and contradicts ADR-0053 (ubiquitous language).
  - _must_address_by_: `implementation`
- **HIGH** `PLAN-ASSUMP-002` (raised in `plan` / `assumption_surfacer`): Regression test test_nudges_couple_exactly_to_shared_infra_suppression only exercises Accepted ADRs (hardcoded via fixture helper). It never exercises the status-mismatch case, so it passed despite the bug shipping in the generated artifact. Test design doesn't cover non-live ADR status values.
  - _must_address_by_: `test design`
- **HIGH** `PLAN-ASSUMP-003` (raised in `plan` / `assumption_surfacer`): Generated artifact docs/arch/generated/adr_xref.md contains false-positive nudges for Superseded ADRs. Either nudges must be filtered for non-live ADRs before output, or the artifact must be regenerated with the corrected logic.
  - _must_address_by_: `implementation`

```json:entry
{"id": "shipped-with-known-gap-pr-10576", "title": "Shipped with known gap \u2014 PR #10576", "topic": "gotchas", "source_type": "shipped-with-known-gap", "source_issue": null, "source_repo": null, "pr_number": 10576, "created_at": "2026-07-26T01:13:28.551583+00:00", "updated_at": "2026-07-26T01:13:28.551583+00:00", "valid_to": null, "superseded_by": null, "superseded_reason": null, "confidence": "high", "stale": false, "corroborations": 1, "concerns": [{"id": "PLAN-ASSUMP-001", "severity": "CRITICAL", "concern": "bare_infra_citation_nudges() has no ADR-status filter while compute_drift restricts to live ADRs only. The shipped artifact (docs/arch/generated/adr_xref.md lines 312-313) shows Superseded ADR-0013 being nudged despite never entering drift-suppression. This directly violates the PR's stated single-source-of-truth invariant and contradicts ADR-0053 (ubiquitous language).", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "implementation"}, {"id": "PLAN-ASSUMP-002", "severity": "HIGH", "concern": "Regression test test_nudges_couple_exactly_to_shared_infra_suppression only exercises Accepted ADRs (hardcoded via fixture helper). It never exercises the status-mismatch case, so it passed despite the bug shipping in the generated artifact. Test design doesn't cover non-live ADR status values.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "test design"}, {"id": "PLAN-ASSUMP-003", "severity": "HIGH", "concern": "Generated artifact docs/arch/generated/adr_xref.md contains false-positive nudges for Superseded ADRs. Either nudges must be filtered for non-live ADRs before output, or the artifact must be regenerated with the corrected logic.", "raised_in_phase": "plan", "raised_in_stage": "assumption_surfacer", "must_address_by": "implementation"}]}
```

