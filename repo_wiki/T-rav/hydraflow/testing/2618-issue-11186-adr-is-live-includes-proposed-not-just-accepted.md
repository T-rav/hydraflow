---
id: 2618
topic: testing
source_issue: 11186
source_phase: plan
created_at: 2026-08-15T00:14:35.607910+00:00
status: active
corroborations: 1
---

# ADR.is_live includes Proposed, not just Accepted

Gate ADR-dependent test logic on `ADR.is_live`, not `status == "Accepted"`. ADR-0044 in `docs/adr` is *Proposed*; an Accepted-only gate silently skips its regression case, and the guard passes because a skip reads as self-retirement.

**Why:** A too-narrow liveness check hides behind `pytest.skip`, trading real coverage for silence.
