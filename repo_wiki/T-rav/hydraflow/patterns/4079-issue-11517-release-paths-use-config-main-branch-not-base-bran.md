---
id: 4079
topic: patterns
source_issue: 11517
source_phase: plan
created_at: 2026-08-21T09:19:56.754272+00:00
status: active
corroborations: 1
---

# Release paths use config.main_branch, not base_branch()

In release/tagging code, use `config.main_branch` directly — never `base_branch()`.

- `src/config.py:6464`'s docstring reserves `main_branch` for "the released/known-good branch".
- `base_branch()` returns the PR merge target (`staging` when `HYDRAFLOW_STAGING_ENABLED=true`, ADR-0042), which is not what a `vX.Y.Z` tag should point at.

**Why:** conflating the two tags the staging SHA or aims the release at the wrong branch, silently reintroducing the #11517 defect under a different name.
