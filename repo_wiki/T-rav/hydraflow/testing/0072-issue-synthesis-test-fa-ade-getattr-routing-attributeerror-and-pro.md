---
id: 0072
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.272011+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Test façade __getattr__ routing, AttributeError, and protocol delegation

When adding a façade over sub-clients, explicitly test: (1) `__getattr__` routes to the correct sub-client, (2) unknown attributes raise `AttributeError`, (3) the façade satisfies protocols via delegation, (4) existing mocks of the original class still pass. Assert sub-components receive mutable dict/set references — not copies — to shared state owned by the façade.

**Why:** Façade delegation bugs pass all pre-existing tests because those tests mock the original class directly, not the façade.
