---
id: 2349
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.100538+00:00
status: active
corroborations: 1
supersedes: 2205
---

# Redirect _find_repo_root to tmp_path for hermetic dotenv tests

For hermetic dotenv tests, monkeypatch `config._find_repo_root` to return a `tmp_path` and write `.env` files there. Never assert against the developer's real checkout `.env`.

Example: mirror new suppression tests beside `test_gh_token_picks_up_dotenv_fallback` and `test_git_identity_picks_up_dotenv_fallback` in `tests/test_config_validation.py`. `tests/regressions/test_issue_10902.py` must pass with 0 skips locally.

**Why:** Asserting against the real `.env` makes tests environment-dependent and masks regressions on machines without those tokens.
