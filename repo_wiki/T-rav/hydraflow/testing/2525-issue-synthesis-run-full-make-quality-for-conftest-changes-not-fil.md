---
id: 2525
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.937276+00:00
status: active
corroborations: 1
supersedes: 2336
---

# Run full make quality for conftest changes, not file-targeted

Any change to `tests/conftest.py` requires `make quality` across the entire suite — a file-targeted pytest subset is not acceptable evidence.

Example: scrubbing previously-ambient keys like `OTEL_*` or `HF_ENV` can break tests that quietly relied on host env values, and this is only caught by the full run. See also: testing — Cross-module PRs require full make quality, not file-targeted.

**Why:** A session-scoped fixture has whole-suite blast radius; partial runs give false confidence.
