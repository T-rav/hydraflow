---
id: 0195
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.787002+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Test façade __getattr__ routing, AttributeError, and protocol delegation

When adding a façade, explicitly test: (1) `__getattr__` routes to the correct sub-client; (2) unknown attributes raise `AttributeError`; (3) the façade satisfies protocols via delegation; (4) existing mocks of the original class still pass. Assert sub-components receive mutable references — not copies — to shared state owned by the façade.

**Why:** Façade delegation bugs pass all pre-existing tests because those tests mock the original class directly, not the façade.
