---
id: 0115
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.085896+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# JS-rendered accessibility attributes require Playwright, not TestClient

Server-side `TestClient` (Django/FastAPI) returns only the initial HTML shell; `aria-labelledby` and other JS-rendered attributes are absent. Delete dead Python `TestClient` tests for these attributes and replace with Playwright tests.

**Why:** TestClient assertions on JS-rendered attributes always pass vacuously — the attribute is missing from the initial render, so assertions check an empty string or missing key.
