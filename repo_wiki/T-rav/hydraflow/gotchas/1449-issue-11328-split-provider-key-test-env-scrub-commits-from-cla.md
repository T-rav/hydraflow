---
id: 1449
topic: gotchas
source_issue: 11328
source_phase: review
created_at: 2026-08-16T12:27:43.693283+00:00
status: active
corroborations: 1
---

# Split provider-key test-env scrub commits from class-folding PRs

Keep commits touching `src/runner_utils.py`, `tests/conftest.py`, and `tests/regressions/test_provider_key_env_scrub.py` in a separate PR from class-key/find-class work — these files have zero class-key or find-class surface.

- The `dcab72bd` quality-fix commit bundled provider API-key env scrub into issue #11328's cross-tick folding PR.

**Why:** Bundled unrelated commits obscure the diff under review and make rollback of one concern impossible without reverting the other.
