---
id: 0043
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.212051+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Test façade __getattr__ routing, AttributeError, and protocol delegation

When adding a façade over sub-clients, explicitly test: (1) `__getattr__` routes to the correct sub-client, (2) unknown attributes raise `AttributeError`, (3) the façade satisfies protocols via delegation, (4) existing mocks of the original class still pass.

Assert sub-components receive mutable dict/set references — not copies — to shared state owned by the façade.

**Why:** Façade delegation bugs pass all pre-existing tests because those tests mock the original class directly, not the façade.
