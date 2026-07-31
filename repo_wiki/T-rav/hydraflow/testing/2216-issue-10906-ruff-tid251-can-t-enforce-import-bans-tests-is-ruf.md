---
id: 2216
topic: testing
source_issue: 10906
source_phase: plan
created_at: 2026-07-31T12:53:04.027141+00:00
status: superseded
corroborations: 1
superseded_by: 2358
---

# ruff TID251 can't enforce import bans — tests/ is ruff-excluded

`tests/regressions` and `tests/trust/adversarial/cases` are ruff-excluded directories, so a `TID251` banned-api rule cannot cover the full test tree. The only viable enforcement point is a pytest-based AST architecture guard (e.g. `tests/architecture/test_tests_have_no_src_prefixed_imports.py`). Pyright also excludes `tests/`, so there is no type-check signal for import hygiene.

**Why:** Relying on linters for test-tree import hygiene leaves excluded subdirectories as silent holes; a pytest guard runs in CI's actual test collection and covers everything.
