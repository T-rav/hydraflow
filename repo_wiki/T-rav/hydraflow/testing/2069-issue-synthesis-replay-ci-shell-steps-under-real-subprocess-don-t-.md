---
id: 2069
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:54.345502+00:00
status: active
corroborations: 1
supersedes: 1944
---

# Replay CI shell steps under real subprocess; don't mock shell

For workflow `run:` bodies in `.github/workflows/*.yml`, extract the `run:` text from the committed YAML and replay it under fake `gh`/`git` binaries via real `subprocess` — no `unittest.mock` of shell execution.

Example: `tests/regressions/test_issue_10881.py` replays the `resolve` step of `rc-promotion-scenario.yml` against CONFLICTING and CLEAN PR fixtures by shimming `PATH` with fake binaries. Sandbox e2e is N/A for GitHub-Actions-resident workflows with no sandbox surface.

**Why:** Mocking the shell hides quoting, env-var expansion, and `set -e` semantics that only the real interpreter surfaces — and that the workflow actually exercises.
