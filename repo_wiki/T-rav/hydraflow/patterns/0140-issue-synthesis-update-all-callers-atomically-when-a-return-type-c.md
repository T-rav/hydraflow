---
id: 0140
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.022653+00:00
status: superseded
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
superseded_by: 0176
---

# Update all callers atomically when a return type changes

When a function's return type changes (e.g., `str | None` → `dict | None`), update every caller in a single commit — never in separate PRs.

Example: change `parse()` return type and grep + update all `result[0]` / `result[1]` unpack sites before committing.

**Why:** A partially-migrated codebase compiles but crashes at runtime on unpatched callers.
