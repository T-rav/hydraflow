---
id: 0883
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:47:48.013504+00:00
status: active
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
---

# Ledger/ADR-drift consolidation PRs require full `make quality`, not targeted subsets

Cleanup/consolidation PRs spanning multiple modules must run full `make quality` (ruff, pyright, tests, jscpd), not just the tests for directly-touched files.

Example: the `src/jsonl_ledger.py` unification (#10403), touching `src/audit/store.py`, `src/escape/ledger.py`, `src/intervention/ledger.py`, `src/erosion/trends.py`, required full quality rather than only `tests/test_escape_ledger.py`/`test_intervention_tally.py`/`test_erosion_trends.py` in isolation — `tests/test_audit_sample_store.py` was needed since `AuditSampleLedger` had only indirect coverage. Same for the #10411 ADR-drift fan-out suppression, over targeted `test_adr_drift.py`/`test_adr_touchpoint_auditor_loop.py`/`test_adr_drift_resolver_loop.py` runs.

**Why:** mirrors the PR #8460/#8463 lesson in CLAUDE.md — a 211-test targeted-file pass went green while `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py` had 7 failures the subset missed; cross-module refactors have wider blast radius than their diff.
