---
id: 0015
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.314227+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Preserve public API during extraction via thin delegation stubs

When extracting code that tests or external callers depend on, keep the original method as a thin stub delegating to the new location.

Example: leave `Client.old_method(self, x)` calling `new_module.old_method(x)` after extraction.

**Why:** Removing public/semi-public methods during refactoring breaks callers that aren't visible in local grep (e.g., dynamically assembled call sites or test mocks).
