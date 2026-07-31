---
id: 0106
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T08:38:28.641656+00:00
status: active
corroborations: 1
supersedes: 0096
---

# Removing src/__init__.py can't close the src.X import alias

Do not attempt to close the `src.X` / `X` alias by deleting `src/__init__.py` or trimming `sys.path`. PEP-420 namespace packages keep `src` importable regardless, and `<repo>` must remain on `sys.path` for `tests.*` and `scripts.*` to resolve.

Example: The only fix is a full rewrite of all 37 `src.`-prefixed import sites to bare canonical, enforced by static AST guards and a `sys.meta_path` blocker.

**Why:** Path surgery cannot eliminate a name that `package-dir` makes canonical at install time.
