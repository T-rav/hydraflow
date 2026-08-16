---
id: 1441
topic: gotchas
source_issue: 11322
source_phase: plan
created_at: 2026-08-16T09:00:07.880208+00:00
status: active
corroborations: 1
---

# ADR exemption lists must be paragraph-scoped, not whole-file

When amending an ADR to list trusted, non-issue-derived exempt modules, format each exemption as its own paragraph — not a comma-separated sentence or bullet list.

The regression test (`tests/regressions/test_issue_11322.py`) second accepted remedy reads paragraphs, not whole-file text. An exempt module named only in a dense list may fail the paragraph match.

Example: in `docs/adr/0092-untrusted-text-trust-boundary.md`, each exempt module (planner, plan_reviewer, triage, reviewer, verification_judge, precheck, acceptance_criteria, ultra_review, report_issue_loop) gets its own paragraph with explicit exemption wording.

**Why:** Paragraph-scoped matching prevents false-positive exemption matches when module names appear in non-exempt contexts elsewhere in the ADR.
