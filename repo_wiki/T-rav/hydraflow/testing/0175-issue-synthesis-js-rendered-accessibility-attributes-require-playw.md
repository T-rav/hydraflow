---
id: 0175
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T06:37:30.581376+00:00
status: superseded
corroborations: 1
supersedes: 0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152
superseded_by: 0183
---

# JS-rendered accessibility attributes require Playwright, not TestClient

Server-side `TestClient` (Django/FastAPI) returns only the initial HTML shell; `aria-labelledby` and other JS-rendered attributes are absent. Delete dead Python `TestClient` tests for these attributes and replace with Playwright tests.

**Why:** TestClient assertions on JS-rendered attributes always pass vacuously — the attribute is missing from the initial render, so assertions check an empty string or missing key.
