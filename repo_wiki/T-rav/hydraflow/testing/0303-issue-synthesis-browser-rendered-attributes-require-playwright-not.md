---
id: 0303
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.880757+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Browser-rendered attributes require Playwright, not TestClient

Server-side `TestClient` (Django/FastAPI) only sees the initial HTML shell; JS-rendered attributes like `aria-labelledby` are absent.

- Delete dead server-side tests that assert JS-rendered HTML; replace with Playwright-based browser tests.

**Why:** TestClient tests for client-rendered attributes always pass vacuously, giving false confidence about real rendering behavior.
