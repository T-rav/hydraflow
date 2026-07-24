---
id: 0843
topic: testing
source_issue: 10449
source_phase: plan
created_at: 2026-07-24T12:33:05.988863+00:00
status: superseded
corroborations: 1
superseded_by: 0847
---

# Gate landings on full `make quality`, never a file-targeted pytest subset

For refactor/landing work touching multiple ledger subclasses (`src/audit/store.py`, `src/escape/ledger.py`, `src/intervention/ledger.py`, `src/erosion/trends.py`), verify with the full `make quality` run, not `pytest tests/test_jsonl_ledger.py tests/test_erosion_trends.py` alone. **Why:** PR #8460 shipped after a 211-test targeted-file pass went green, but `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py` had 7 failures the subset missed, forcing hotfix PR #8463 — cross-module refactors have wider blast radius than their diff.
