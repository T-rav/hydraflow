---
id: 0343
topic: architecture
source_issue: 11193
source_phase: plan
created_at: 2026-08-15T00:39:44.183371+00:00
status: active
corroborations: 1
---

# Resolve transitive repo root constants in AST scans

When scanning for path pins, implement two-pass module-level name resolution to catch both direct and transitive root bindings.

- Direct: `Path(__file__)...parents[N] / "docs" / "adr"`
- Transitive: `_REPO_ROOT = Path(__file__)...parents[N]`; then `_REPO_ROOT / "docs" / "adr"`
- Skipping the transitive shape misses known offenders like `test_issue_9419_9421_adr_drift.py:49-50`.

**Why:** Handling only direct `Path(__file__)` bindings makes the guard blind to real offenders and passes green against existing defects.
