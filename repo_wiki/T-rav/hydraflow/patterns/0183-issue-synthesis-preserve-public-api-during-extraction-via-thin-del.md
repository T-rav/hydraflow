---
id: 0183
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:22:06.630746+00:00
status: superseded
corroborations: 1
supersedes: 0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175
superseded_by: 0218
---

# Preserve public API during extraction via thin delegation stubs

When extracting code that tests or external callers depend on, keep the original method as a thin stub delegating to the new location.

Example: leave `Client.old_method(self, x)` calling `new_module.old_method(x)` after extraction.

**Why:** Removing public/semi-public methods during refactoring breaks callers that aren't visible in local grep (e.g., dynamically assembled call sites or test mocks).
