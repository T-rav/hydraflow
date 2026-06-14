---
id: 0020
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.315212+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Retarget mock patches to the new location before moving a method

Before moving a method to a new module, update all `@patch` decorators in tests to point to the destination path, then move the implementation.

Example: change `@patch('old.module.Method')` → `@patch('new.module.Method')` before the move commit.

**Why:** Moving a method without updating patches leaves tests patching a now-unused import, so the live code runs unpatched and the test silently stops covering the real path.
