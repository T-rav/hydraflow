---
id: 0085
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.275614+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# JS-rendered accessibility attributes require Playwright, not TestClient

Server-side `TestClient` (Django/FastAPI) returns only the initial HTML shell; `aria-labelledby` and other JS-rendered attributes are absent. Delete dead Python `TestClient` tests for these attributes and replace with Playwright tests.

**Why:** TestClient assertions on JS-rendered attributes always pass vacuously — the attribute is missing from the initial render, so assertions check an empty string or missing key.
