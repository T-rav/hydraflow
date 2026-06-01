---
source: feedback_make_audit_separate_from_quality.md
name: feedback_make_audit_separate_from_quality
description: CI's "Principles Audit" runs `make audit` — NOT part of `make quality`; run it on convention/CI/workflow-touching PRs
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-05-31'
---

CI's **"Principles Audit"** job runs `make audit` (`scripts/hydraflow_audit`), which is **NOT** part of `make quality`. A PR can pass full `make quality` (lint/typecheck/security/~15k tests) and still fail CI on Principles Audit.

**Why:** `make audit` checks repo-wide conventions (P1–P10) against the live tree — e.g. P5.2 "a workflow runs `make quality-lite` or equivalent", P5.3 coverage gate, layer-check, etc. These are policy checks, not in the quality pipeline.

**How to apply:** any PR that touches `.github/workflows/`, `Makefile` targets, hooks, or repo conventions MUST run `make audit` locally before pushing — `make quality` alone will miss it. Caught on PR #9131 (factory CI refinements): C-3 unified CI onto `make quality` (replacing `quality-lite` in quality.yml), which made P5.2 fail because the check literally grepped for `quality-lite`. Fix was to teach P5.2 that `make quality` (a superset) satisfies the principle's own "or equivalent" clause + a unit test — NOT to revert the unification. (Updating a too-literal audit check to honor its documented principle is not loosening; see [[feedback_plans_are_flexible]].)

Related discipline: [[feedback_cleanup_prs_need_full_suite]], [[feedback_make_quality_pipe_exit_code]].
