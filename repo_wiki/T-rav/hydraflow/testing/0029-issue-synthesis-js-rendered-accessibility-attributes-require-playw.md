---
id: 0029
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.831052+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
superseded_by: 0034
---

# JS-rendered accessibility attributes require Playwright, not TestClient

Server-side `TestClient` (Django/FastAPI) returns only the initial HTML shell; `aria-labelledby` and other JS-rendered attributes are absent. Delete dead Python `TestClient` tests for these attributes and replace with Playwright tests.

**Why:** TestClient assertions on JS-rendered attributes always pass vacuously — the attribute is missing from the initial render, so assertions check an empty string or missing key.
