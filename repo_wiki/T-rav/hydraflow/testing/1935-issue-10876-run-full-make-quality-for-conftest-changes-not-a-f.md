---
id: 1935
topic: testing
source_issue: 10876
source_phase: plan
created_at: 2026-07-31T05:37:16.290834+00:00
status: superseded
corroborations: 1
superseded_by: 2062
---

# Run full make quality for conftest changes, not a file-targeted subset

Any change to `tests/conftest.py` requires `make quality` across the entire suite — a file-targeted pytest subset is not acceptable evidence. Scrubbing previously-ambient keys like `OTEL_*` or `HF_ENV` can break tests that quietly relied on host env values, and this is only caught by the full run. **Why:** a session-scoped fixture has whole-suite blast radius; partial runs give false confidence.
