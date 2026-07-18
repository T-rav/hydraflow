---
id: 0264
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:34:51.007829+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Browser-rendered attributes require Playwright, not TestClient

Delete dead server-side tests that assert JS-rendered HTML; replace with Playwright-based browser tests.

Example: Server-side `TestClient` only sees the initial HTML shell; JS-rendered attributes like `aria-labelledby` are absent.

**Why:** TestClient tests for client-rendered attributes always pass vacuously, giving false confidence about real rendering behavior.
