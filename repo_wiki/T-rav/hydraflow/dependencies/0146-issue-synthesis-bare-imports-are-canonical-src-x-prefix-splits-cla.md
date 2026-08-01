---
id: 0146
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:41:45.186505+00:00
status: active
corroborations: 1
supersedes: 0135
---

# Bare imports are canonical; src.X prefix splits class identity

Use bare imports (`from pending_concerns import Concern`), never `from src.pending_concerns import Concern` — the setuptools `package-dir={"" = "src"}` install makes bare names canonical.

Example: `src/models.py` typed `AdversarialState.pending_concerns` as `src.pending_concerns.Concern`; `src/adversarial_retry_loop.py` built `pending_concerns.Concern`; result: two distinct class objects, live `ValidationError` in production. See also: dependencies — Removing src/__init__.py can't close the src.X import alias.

**Why:** Two import paths produce two separate class objects even with identical source code, breaking `isinstance` and Pydantic validation.
