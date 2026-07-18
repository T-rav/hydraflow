---
id: 0056
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:15:44.524807+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Update all callers atomically when a return type changes

When a function's return type changes (e.g., `str | None` → `dict | None`), update every caller in a single commit — never in separate PRs.

Example: change `parse()` return type and grep + update all `result[0]` / `result[1]` unpack sites before committing.

**Why:** A partially-migrated codebase compiles but crashes at runtime on unpatched callers.
