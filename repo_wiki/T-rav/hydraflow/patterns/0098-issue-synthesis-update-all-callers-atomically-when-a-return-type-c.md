---
id: 0098
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:07:53.442438+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Update all callers atomically when a return type changes

When a function's return type changes (e.g., `str | None` → `dict | None`), update every caller in a single commit — never in separate PRs.

Example: change `parse()` return type and grep + update all `result[0]` / `result[1]` unpack sites before committing.

**Why:** A partially-migrated codebase compiles but crashes at runtime on unpatched callers.
