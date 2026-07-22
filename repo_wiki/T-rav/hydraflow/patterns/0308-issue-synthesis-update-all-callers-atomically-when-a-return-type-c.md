---
id: 0308
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:37:54.867768+00:00
status: active
corroborations: 1
supersedes: 0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294,0295,0296,0297,0298,0299,0300,0301
---

# Update all callers atomically when a return type changes

When a function's return type changes, update every caller in a single commit — never in separate PRs.

Example: Change `parse()` return type and grep + update all `result[0]` / `result[1]` unpack sites before committing.

**Why:** A partially-migrated codebase compiles but crashes at runtime on unpatched callers.
