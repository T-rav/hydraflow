---
id: 2657
topic: testing
source_issue: 11277
source_phase: plan
created_at: 2026-08-15T21:08:01.026789+00:00
status: active
corroborations: 1
---

# No gh/git/subprocess outside the shared adapter (hexagonal)

All `gh`, `git`, and subprocess calls for the rails-health-fix feature must live inside the adapter shipped by #11276. `RepoHealthPanel.jsx` and `hydraflow_healthcheck/__main__.py` must not shell out directly. The CLI imports the adapter's public interface; the UI POSTs to `/api/rails-health/fix`.
**Why:** Hexagonal isolation keeps external-tool calls testable via fakes (`FakeGitHub`, `BotPRPort`) and prevents subprocess leaks across slices.
