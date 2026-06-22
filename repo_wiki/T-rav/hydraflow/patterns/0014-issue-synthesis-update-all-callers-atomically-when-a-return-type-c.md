---
id: 0014
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.314046+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Update all callers atomically when a return type changes

When a function's return type changes (e.g., `str | None` → `dict | None`), update every caller in a single commit — never in separate PRs.

Example: change `parse()` return type and grep + update all `result[0]` / `result[1]` unpack sites before committing.

**Why:** A partially-migrated codebase compiles but crashes at runtime on unpatched callers.
