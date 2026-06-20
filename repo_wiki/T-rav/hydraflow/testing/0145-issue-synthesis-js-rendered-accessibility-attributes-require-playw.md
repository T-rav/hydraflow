---
id: 0145
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-15T05:57:54.438376+00:00
status: superseded
corroborations: 1
supersedes: 0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122
superseded_by: 0153
---

# JS-rendered accessibility attributes require Playwright, not TestClient

Server-side `TestClient` (Django/FastAPI) returns only the initial HTML shell; `aria-labelledby` and other JS-rendered attributes are absent. Delete dead Python `TestClient` tests for these attributes and replace with Playwright tests.

**Why:** TestClient assertions on JS-rendered attributes always pass vacuously — the attribute is missing from the initial render, so assertions check an empty string or missing key.
