---
id: 0385
topic: architecture
source_issue: 11332
source_phase: plan
created_at: 2026-08-16T10:18:33.580070+00:00
status: active
corroborations: 1
---

# Architecture tests use AST guards with self-retiring baselines

Use `tests/architecture/test_*.py` modules that AST-scan `src/` for invariant violations, backed by a `_UNDECLARED_BASELINE` dict mapping `key → justification`. Pair the guard with a staleness ratchet that fails when a baseline entry's site no longer violates.

- `test_adr0092_restricted_declaration.py` (ADR-0092) and `test_adr_enforcement_ratchet.py` follow this shape.
- Assertion messages must name the exact remedy (e.g. "delete this stale `_UNDECLARED_BASELINE` entry") so sibling PRs know what to do.

**Why:** Silent drift in `src/` re-introduces the defect; the ratchet ensures the baseline only shrinks, never grows.
