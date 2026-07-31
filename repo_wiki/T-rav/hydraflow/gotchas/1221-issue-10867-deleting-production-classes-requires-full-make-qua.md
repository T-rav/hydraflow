---
id: 1221
topic: gotchas
source_issue: 10867
source_phase: plan
created_at: 2026-07-31T03:20:17.216757+00:00
status: active
corroborations: 1
---

# Deleting production classes requires full make quality, not targeted tests

Deleting production classes (e.g., `ADRValidationIssue`/`ADRValidationResult` from `src/models.py`, where live defs are `@dataclass`es in `src/adr_pre_validator.py`) requires full `make quality`, not a file-targeted test subset. Even after grep-verifying no direct imports, `__all__`/dynamic re-export consumers can break silently. This is the PR #8460 lesson documented in CLAUDE.md.

**Why:** Targeted test runs miss transitive import paths that only surface in the full suite.
