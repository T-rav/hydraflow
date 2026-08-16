---
id: 1465
topic: gotchas
source_issue: 11328
source_phase: review
created_at: 2026-08-16T12:27:43.693283+00:00
status: active
corroborations: 1
---

# Split provider-key test-env scrub commits from class-folding PRs, unless the branch's own quality gate depends on them

Keep commits touching `src/runner_utils.py`, `tests/conftest.py`, and `tests/regressions/test_provider_key_env_scrub.py` in a separate PR from class-key/find-class work — these files have zero class-key or find-class surface.

- The `dcab72bd` quality-fix commit bundled provider API-key env scrub into issue #11328's cross-tick folding PR.
- **Exception:** a gate-unblocking `quality-fix:`-prefixed commit may ride along when the *branch's own* `make quality` fails without it — reviewed and confirmed for `dcab72bd`: in a shell with ambient `ZAI_CODING_PLAN_KEY` exported, `tests/test_llm_provider.py`'s `test_resolve_harness_env_missing_key_falls_open` fails without the `tests/conftest.py` scrub, since only `ZAI_API_KEY`/`HYDRAFLOW_ZAI_API_KEY` were previously delenv'd, not the bare coding-plan key. Reverting to "split cleanly" would just make the next agent on this branch re-discover and re-land the identical fix. Splitting still applies when the branch's own gate does not depend on the change.

**Why:** Bundled unrelated commits obscure the diff under review and make rollback of one concern impossible without reverting the other — but a gate-unblocking exception avoids a revert/re-land churn loop when the fix is load-bearing for this branch's own quality gate.
