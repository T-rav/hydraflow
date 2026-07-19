---
id: 0225
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:45:28.220070+00:00
status: superseded
corroborations: 1
supersedes: 0176,0177,0178,0179,0180,0181,0182,0183,0184,0185,0186,0187,0188,0189,0190,0191,0192,0193,0194,0195,0196,0197,0198,0199,0200,0201,0202,0203,0204,0205,0206,0207,0208,0209,0210,0211,0212,0213,0214,0215,0216,0217
superseded_by: 0260
---

# Preserve public API during extraction via delegation stubs

When extracting code that tests or external callers depend on, keep the original method as a thin stub delegating to the new location.

Example: Leave `Client.old_method(self, x)` calling `new_module.old_method(x)` after extraction.

**Why:** Removing public/semi-public methods during refactoring breaks callers that aren't visible in local grep (e.g., dynamically assembled call sites or test mocks).
