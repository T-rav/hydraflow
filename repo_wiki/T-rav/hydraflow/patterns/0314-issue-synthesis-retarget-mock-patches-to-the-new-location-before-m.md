---
id: 0314
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:37:54.870724+00:00
status: active
corroborations: 1
supersedes: 0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294,0295,0296,0297,0298,0299,0300,0301
---

# Retarget mock patches to the new location before moving a method

Before moving a method to a new module, update all `@patch` decorators in tests to point to the destination path, then move the implementation.

Example: Change `@patch('old.module.Method')` → `@patch('new.module.Method')` before the move commit.

**Why:** Moving a method without updating patches leaves tests patching a now-unused import, so the live code runs unpatched and the test silently stops covering the real path.
