---
id: 2654
topic: testing
source_issue: 11276
source_phase: plan
created_at: 2026-08-15T21:04:18.934665+00:00
status: active
corroborations: 1
---

# Test subprocess edges with real git tmp repos, not MockWorld

For code that shells out to git/gh (e.g. `CrossRepoBotPRPort`), write adapter tests with real git tmp repos + bare origins + a fake-gh shim. Grep `tests/conftest.py` for existing helpers first. MockWorld's fakes operate at the Port protocol level and cannot exercise the subprocess boundary.

**Why:** A fake `BotPRPort` passing tests doesn't prove real git worktree/branch/push isolation holds — only real git operations verify the structural safety properties.
