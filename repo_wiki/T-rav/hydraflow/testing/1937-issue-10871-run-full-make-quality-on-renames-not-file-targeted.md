---
id: 1937
topic: testing
source_issue: 10871
source_phase: plan
created_at: 2026-07-31T06:30:13.825325+00:00
status: active
corroborations: 1
---

# Run full make quality on renames, not file-targeted subsets

For rename/cleanup changes whose blast radius exceeds the diff (e.g. promoting `_load_audit_module` → `load_audit_module` across `src/prompt_fitness.py` and `tests/`), run full `make quality`, not a file-targeted pytest subset.

PR #8460 lesson: file-targeted runs miss cross-module references and lint regressions that the full gate catches.

**Why:** Rename blast radius is wider than the touched files; a green targeted run is a false signal that the cleanup is complete.
