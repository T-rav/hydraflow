---
id: 2076
topic: testing
source_issue: 10902
source_phase: plan
created_at: 2026-07-31T11:38:13.878531+00:00
status: superseded
corroborations: 1
superseded_by: 2205
---

# Redirect _find_repo_root to tmp_path for hermetic dotenv tests

For hermetic dotenv tests, monkeypatch `config._find_repo_root` to return a `tmp_path` and write `.env` files there. Never assert against the developer's real checkout `.env`.

- Mirror new suppression tests beside `test_gh_token_picks_up_dotenv_fallback` and `test_git_identity_picks_up_dotenv_fallback` in `tests/test_config_validation.py`.
- Those existing tests are counter-pins: they use explicit `repo_root` and must stay green.
- `tests/regressions/test_issue_10902.py` must pass with 0 skips locally; a local skip means the pure reader got suppressed.

**Why:** Asserting against the real `.env` makes tests environment-dependent and masks regressions on machines without those tokens.
