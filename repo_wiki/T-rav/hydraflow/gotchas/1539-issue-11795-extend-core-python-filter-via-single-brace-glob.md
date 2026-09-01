---
id: 1539
topic: gotchas
source_issue: 11795
source_phase: plan
created_at: 2026-08-30T07:41:57.361414+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Extend core_python filter via single brace-glob

Extend the `core_python` path filter in `.github/workflows/ci.yml` using a single brace-glob, not a new line. The filter uses `predicate-quantifier: every` and is constrained by the `core_python ⊆ python` subset invariant.

**Why:** Adding a separate line breaks the "Filter subset invariant" build step and causes failures on gates-only PRs.
