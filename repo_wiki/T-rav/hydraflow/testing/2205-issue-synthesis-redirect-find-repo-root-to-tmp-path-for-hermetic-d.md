---
id: 2205
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T14:26:19.464470+00:00
status: superseded
corroborations: 1
supersedes: 2076
superseded_by: 2349
---

# Redirect _find_repo_root to tmp_path for hermetic dotenv tests

For hermetic dotenv tests, monkeypatch `config._find_repo_root` to return a `tmp_path` and write `.env` files there. Never assert against the developer's real checkout `.env`.

Example: Mirror new suppression tests beside `test_gh_token_picks_up_dotenv_fallback` and `test_git_identity_picks_up_dotenv_fallback` in `tests/test_config_validation.py`. Those existing tests are counter-pins: they use explicit `repo_root` and must stay green. `tests/regressions/test_issue_10902.py` must pass with 0 skips locally.

**Why:** Asserting against the real `.env` makes tests environment-dependent and masks regressions on machines without those tokens.
