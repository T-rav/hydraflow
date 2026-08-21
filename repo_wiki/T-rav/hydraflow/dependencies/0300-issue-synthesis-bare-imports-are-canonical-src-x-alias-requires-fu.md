---
id: 0300
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-21T11:38:32.598356+00:00
status: active
corroborations: 1
supersedes: 0281,0282
---

# Bare imports are canonical; src.X alias requires full rewrite

Use bare imports only (`from pending_concerns import Concern`), never `src.`-prefixed. Do not attempt to close the alias by deleting `src/__init__.py` — the only fix is rewriting all import sites.

Example: Two import paths produce distinct class objects (`src.pending_concerns.Concern` vs `pending_concerns.Concern`), causing `ValidationError` when mixed. PEP-420 namespace packages keep `src` importable; `<repo>` stays on `sys.path` for `tests.*` and `scripts.*`.

**Why:** `package-dir={"": "src"}` makes bare names canonical at install time; path surgery cannot override this, breaking `isinstance` checks and Pydantic validation.
