---
id: 0102
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.082128+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Test façade __getattr__ routing, AttributeError, and protocol delegation

When adding a façade over sub-clients, explicitly test: (1) `__getattr__` routes to the correct sub-client, (2) unknown attributes raise `AttributeError`, (3) the façade satisfies protocols via delegation, (4) existing mocks of the original class still pass. Assert sub-components receive mutable dict/set references — not copies — to shared state owned by the façade.

**Why:** Façade delegation bugs pass all pre-existing tests because those tests mock the original class directly, not the façade.
