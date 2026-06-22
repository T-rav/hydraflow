---
id: 0162
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.577187+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# Test façade __getattr__ routing, AttributeError, and protocol delegation

When adding a façade over sub-clients, explicitly test: (1) `__getattr__` routes to the correct sub-client, (2) unknown attributes raise `AttributeError`, (3) the façade satisfies protocols via delegation, (4) existing mocks of the original class still pass. Assert sub-components receive mutable dict/set references — not copies — to shared state owned by the façade.

**Why:** Façade delegation bugs pass all pre-existing tests because those tests mock the original class directly, not the façade.
