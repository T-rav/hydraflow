---
id: 0096
topic: dependencies
source_issue: 10874
source_phase: plan
created_at: 2026-07-31T06:49:10.357893+00:00
status: active
corroborations: 1
---

# Removing src/__init__.py can't close the src.X import alias

Do not attempt to close the `src.X` / `X` alias by deleting `src/__init__.py` or trimming `sys.path`. PEP-420 namespace packages keep `src` importable regardless, and `<repo>` must remain on `sys.path` for `tests.*` and `scripts.*` to resolve.

The only fix is a full rewrite of all `src.`-prefixed import sites (37 in this repo) to bare canonical, enforced by static AST guards and a `sys.meta_path` blocker.

**Why:** Path surgery cannot eliminate a name that `package-dir` makes canonical at install time.
