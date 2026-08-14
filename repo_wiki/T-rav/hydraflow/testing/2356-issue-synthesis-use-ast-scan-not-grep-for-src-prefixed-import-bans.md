---
id: 2356
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.119553+00:00
status: superseded
corroborations: 1
supersedes: 2214
superseded_by: 2545
---

# Use AST scan not grep for src-prefixed import bans in tests/

Enforce a `src.`-import ban under `tests/` via an AST walk (`ast.Import`/`ast.ImportFrom` with `level == 0` rooted at `src`), not a text grep.

Example: `tests/test_ubiquitous_language.py` has ~30 `src.mkdir()` local-variable lines that a regex scan would flag as false positives.

**Why:** Text-based import detection produces unactionable noise in files that use `src` as a variable name, undermining the guard's credibility and making real offenders ignorable.
