---
id: 2062
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:54.226053+00:00
status: superseded
corroborations: 1
supersedes: 1935
superseded_by: 2191
---

# Run full make quality for conftest changes, not file-targeted

Any change to `tests/conftest.py` requires `make quality` across the entire suite — a file-targeted pytest subset is not acceptable evidence.

Example: Scrubbing previously-ambient keys like `OTEL_*` or `HF_ENV` can break tests that quietly relied on host env values, and this is only caught by the full run.

**Why:** A session-scoped fixture has whole-suite blast radius; partial runs give false confidence.
