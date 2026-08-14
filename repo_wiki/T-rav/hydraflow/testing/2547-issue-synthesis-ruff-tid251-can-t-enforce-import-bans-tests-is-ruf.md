---
id: 2547
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.271703+00:00
status: active
corroborations: 1
supersedes: 2358
---

# ruff TID251 can't enforce import bans — tests/ is ruff-excluded

`tests/regressions` and `tests/trust/adversarial/cases` are ruff-excluded directories, so a `TID251` banned-api rule cannot cover the full test tree. The only viable enforcement point is a pytest-based AST architecture guard (e.g. `tests/architecture/test_tests_have_no_src_prefixed_imports.py`).

**Why:** Relying on linters for test-tree import hygiene leaves excluded subdirectories as silent holes; a pytest guard runs in CI's actual test collection and covers everything.
