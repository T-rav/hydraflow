---
id: 0016
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.828759+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# Test façade __getattr__ routing, AttributeError, and protocol delegation

When adding a façade over sub-clients, explicitly test: (1) `__getattr__` routes calls to the correct sub-client, (2) unknown attributes raise `AttributeError`, (3) the façade satisfies protocols via delegation, (4) existing mocks of the original class still pass.

Assert sub-components receive mutable dict/set references, not copies, to shared state owned by the façade.

**Why:** Façade delegation bugs pass all pre-existing tests because those tests mock the original class directly, not the façade.
