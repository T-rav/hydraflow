---
id: 0182
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:22:06.630414+00:00
status: active
corroborations: 1
supersedes: 0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175
---

# Update all callers atomically when a return type changes

When a function's return type changes (e.g., `str | None` → `dict | None`), update every caller in a single commit — never in separate PRs.

Example: change `parse()` return type and grep + update all `result[0]` / `result[1]` unpack sites before committing.

**Why:** A partially-migrated codebase compiles but crashes at runtime on unpatched callers.
