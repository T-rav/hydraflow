---
id: 1944
topic: testing
source_issue: 10881
source_phase: plan
created_at: 2026-07-31T07:22:08.358172+00:00
status: superseded
corroborations: 1
superseded_by: 2069
---

# Replay CI shell steps under real subprocess; don't mock the shell

Rule: For workflow `run:` bodies in `.github/workflows/*.yml`, extract the `run:` text from the committed YAML and replay it under fake `gh`/`git` binaries via real `subprocess` — no `unittest.mock` of shell execution. This is the repo convention for git/CI shell code.

Example:
- `tests/regressions/test_issue_10881.py` replays the `resolve` step of `rc-promotion-scenario.yml` against CONFLICTING and CLEAN PR fixtures by shimming `PATH` with fake binaries.
- Sandbox e2e is N/A for GitHub-Actions-resident workflows with no sandbox surface; the subprocess replay is the top layer.

**Why:** Mocking the shell hides quoting, env-var expansion, and `set -e` semantics that only the real interpreter surfaces — and that the workflow actually exercises.
