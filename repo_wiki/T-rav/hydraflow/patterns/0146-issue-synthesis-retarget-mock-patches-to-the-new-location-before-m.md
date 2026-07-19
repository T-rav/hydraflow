---
id: 0146
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.024404+00:00
status: superseded
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
superseded_by: 0176
---

# Retarget mock patches to the new location before moving a method

Before moving a method to a new module, update all `@patch` decorators in tests to point to the destination path, then move the implementation.

Example: change `@patch('old.module.Method')` → `@patch('new.module.Method')` before the move commit.

**Why:** Moving a method without updating patches leaves tests patching a now-unused import, so the live code runs unpatched and the test silently stops covering the real path.
