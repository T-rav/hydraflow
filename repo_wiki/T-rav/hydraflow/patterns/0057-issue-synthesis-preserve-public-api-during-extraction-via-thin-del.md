---
id: 0057
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:15:44.525330+00:00
status: superseded
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
superseded_by: 0092
---

# Preserve public API during extraction via thin delegation stubs

When extracting code that tests or external callers depend on, keep the original method as a thin stub delegating to the new location.

Example: leave `Client.old_method(self, x)` calling `new_module.old_method(x)` after extraction.

**Why:** Removing public/semi-public methods during refactoring breaks callers that aren't visible in local grep (e.g., dynamically assembled call sites or test mocks).
