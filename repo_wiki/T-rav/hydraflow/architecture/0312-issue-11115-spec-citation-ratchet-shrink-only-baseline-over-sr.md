---
id: 0312
topic: architecture
source_issue: 11115
source_phase: plan
created_at: 2026-08-14T10:03:17.496107+00:00
status: active
corroborations: 1
---

# Spec citation ratchet: shrink-only baseline over src/*.py

Use a shrink-only baseline to drain unresolved `§` citations from `src/*.py`. The resolver in `src/spec_citation.py` checks that every `§` in a module resolves to a heading in the `Spec:`-declared design doc, and `tests/architecture/test_spec_citations_resolve.py` enforces that unresolved citations never exceed `tests/architecture/spec_citation_baseline.json` (mirrors `test_adr_source_citations_exist.py`). Scan top-level `src/*.py` only — `src/ui/node_modules` also contains `§` and must be excluded.

**Why:** Without a ratchet, a 45-file cleanup either lands as one massive PR or never lands at all.
