---
id: 0215
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T04:51:57.143666+00:00
status: superseded
corroborations: 1
supersedes: 0200
superseded_by: 0230
---

# Removing src/__init__.py can't close the src.X import alias

Do not attempt to close the `src.X` / `X` alias by deleting `src/__init__.py` or trimming `sys.path` — the only fix is a full rewrite of all `src.`-prefixed import sites to bare canonical.

Example: PEP-420 namespace packages keep `src` importable regardless; `<repo>` must remain on `sys.path` for `tests.*` and `scripts.*`. Enforced by static AST guards and a `sys.meta_path` blocker. See also: dependencies — Bare imports are canonical; src.X prefix splits class identity.

**Why:** Path surgery cannot eliminate a name that `package-dir` makes canonical at install time.
