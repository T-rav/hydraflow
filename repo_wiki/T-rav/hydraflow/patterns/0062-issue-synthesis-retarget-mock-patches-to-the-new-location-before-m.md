---
id: 0062
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:57:29.425480+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Retarget mock patches to the new location before moving a method

Before moving a method to a new module, update all `@patch` decorators in tests to point to the destination path, then move the implementation.

Example: change `@patch('old.module.Method')` → `@patch('new.module.Method')` before the move commit.

**Why:** Moving a method without updating patches leaves tests patching a now-unused import, so the live code runs unpatched and the test silently stops covering the real path.
