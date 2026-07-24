---
id: 0630
topic: testing
source_issue: 10403
source_phase: plan
created_at: 2026-07-24T05:36:17.563802+00:00
status: active
corroborations: 1
---

# Verify JSONL-store cleanups with full `make quality`, not a targeted subset

For the `src/jsonl_ledger.py` unification (issue #10403), the plan explicitly requires full `make quality` (ruff, pyright, tests, jscpd) rather than running just `tests/test_escape_ledger.py` / `tests/test_intervention_tally.py` / `tests/test_erosion_trends.py` in isolation, and adds `tests/test_audit_sample_store.py` since `AuditSampleLedger` previously had only indirect coverage.

**Why:** per CLAUDE.md, cleanup PRs have historically over-pruned code where a file-targeted subset passed but unrelated suites (e.g. PR #8460) broke.
