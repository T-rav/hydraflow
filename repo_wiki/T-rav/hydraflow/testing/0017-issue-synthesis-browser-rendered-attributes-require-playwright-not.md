---
id: 0017
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.409494+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Browser-rendered attributes require Playwright, not TestClient

Server-side `TestClient` (Django/FastAPI) only sees the initial HTML shell. Accessibility attributes like `aria-labelledby` set by JavaScript are absent.

Delete dead server-side tests that assert JS-rendered HTML; replace with Playwright-based browser tests.

**Why:** TestClient tests for client-rendered attributes always pass vacuously, giving false confidence about real rendering behavior.
