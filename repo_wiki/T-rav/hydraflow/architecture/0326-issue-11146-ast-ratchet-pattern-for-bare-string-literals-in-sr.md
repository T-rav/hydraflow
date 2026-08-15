---
id: 0326
topic: architecture
source_issue: 11146
source_phase: plan
created_at: 2026-08-14T15:08:46.026963+00:00
status: active
corroborations: 1
---

# AST ratchet pattern for bare string literals in src/

Lock config-migrated literals with an AST scan over `src/**/*.py` that collects `ast.Constant` string nodes matching the literal, skipping any that are `.value` of an `ast.Expr` (docstrings/comments). Precedent: `tests/test_pr_base_branch_convention.py`.

- Allowlist is `{module: tracking_issue}`, asserted in both directions so it shrinks as modules are fixed.
- Each allowlist entry is self-retiring: a fixed module must be removed.

**Why:** Prevents a rename from re-scattering bare literals across `src/` modules after a config-backed SSOT is introduced.
