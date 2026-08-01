---
id: 2214
topic: testing
source_issue: 10906
source_phase: plan
created_at: 2026-07-31T12:53:04.027117+00:00
status: superseded
corroborations: 1
superseded_by: 2356
---

# Use AST scan not grep for src-prefixed import bans in tests/

Enforce a `src.`-import ban under `tests/` via an AST walk (`ast.Import`/`ast.ImportFrom` with `level == 0` rooted at `src`), not a text grep. `tests/test_ubiquitous_language.py` has ~30 `src.mkdir()` local-variable lines that a regex scan would flag as false positives.

**Why:** Text-based import detection produces unactionable noise in files that use `src` as a variable name, undermining the guard's credibility and making real offenders ignorable.
